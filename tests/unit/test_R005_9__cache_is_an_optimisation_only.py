"""R5.9 — deleting the cache directory changes no output.

The cache is an optimisation and never a source of truth. If deleting it changes
an answer, something is being remembered that should have been derived.

This is the rule that makes the cache safe to distrust. Any time an answer looks
wrong, the first thing anyone will try is deleting `.dossier/cache/` — and that
has to be a free action, costing time and nothing else. A cache holding something
underived turns that instinct into a way of losing work.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8, "INC-4822": "77c1b40a" * 8}
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)

TEXT = {key: STAGE_INPUTS["INC-4821"] + f"\n\nFiled as {key}.\n" for key in DOCUMENTS}


def answer(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "loss_amount",
                    "value": 48200.00,
                    "currency": "CHF",
                    "source": {"document": "INC-4821", "span": LOSS_SPAN},
                }
            ],
        }
    )


def pipeline(*steps: tuple[str, str]) -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(id=name, prompt=f"prompts/{name}.md", input=value, mode="per_file")
            for name, value in steps
        ],
    )


def run(workspace: Path, model, *, config, run_id: str):
    return execute(
        workspace=workspace,
        pipeline=config,
        pipeline_hash=PIPELINE_HASH,
        documents=DOCUMENTS,
        document_text=TEXT,
        schemas=dict.fromkeys([step.id for step in config.steps], SCHEMA),
        prompts={step.id: prompt_for(step.inputs) for step in config.steps},
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


def outputs(report) -> list[tuple]:
    """Everything a caller gets back, minus how it was obtained.

    `attempts` is excluded on purpose: it is exactly the difference the rule
    permits, and including it would make the assertion trivially false.

    The artifact bytes are included via `_as_text`, because R5.9 row 1 says
    "byte-identical artifacts" and this helper previously compared parsed
    records -- which two different serialisations of the same fields would
    satisfy.
    """
    from dossier.application.run import _as_text

    return [
        (
            step.step,
            result.document,
            result.records,
            result.checks,
            result.error,
            None if result.failed else _as_text(result),
        )
        for step in report.steps
        for result in step.results
    ]


def artifact_bytes(workspace: Path) -> dict[str, bytes]:
    """Every cached artifact, by cache key, excluding provenance records."""
    root = workspace / ".dossier" / "cache" / "stage"
    return {
        path.name: path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith(".meta.json")
    }


def scrub(workspace: Path) -> None:
    shutil.rmtree(workspace / ".dossier" / "cache")


class TestDeletingTheCacheChangesNothing:
    """R5.9 — time is the only thing it costs."""

    def test_the_same_run_after_deleting_the_cache_produces_the_same_output(
        self, tmp_path: Path
    ):
        """Example 1: the one where the answers have to match exactly."""
        config = pipeline(("extract", "documents"), ("verify", "previous"))
        first = run(
            tmp_path,
            FakeModelClient(responses=[answer(key) for key in ["INC-4821", "INC-4822"] * 2]),
            config=config,
            run_id="20260806T142203Z-4f1a",
        )

        stored = artifact_bytes(tmp_path)
        scrub(tmp_path)
        again = run(
            tmp_path,
            FakeModelClient(responses=[answer(key) for key in ["INC-4821", "INC-4822"] * 2]),
            config=config,
            run_id="20260907T090000Z-bbbb",
        )

        assert outputs(again) == outputs(first)
        # And on disk: the same keys holding the same bytes, rebuilt from
        # scratch. Row 1 says "byte-identical artifacts", and structural
        # equality of parsed records is a weaker claim that two different
        # serialisations of the same fields would satisfy.
        assert artifact_bytes(tmp_path) == stored

    def test_the_only_difference_is_the_model_calls(self, tmp_path: Path):
        """Example 2: the one that measures what deleting it actually costs.

        Four calls the first time, none the second, four again after the cache is
        gone. That is the whole difference, and stating it as a count is what
        stops "no output changed" being satisfied by a run that did nothing.
        """
        config = pipeline(("extract", "documents"), ("verify", "previous"))
        responses = [answer(key) for key in ["INC-4821", "INC-4822"] * 2]

        cold = FakeModelClient(responses=list(responses))
        run(tmp_path, cold, config=config, run_id="20260806T142203Z-4f1a")

        warm = FakeModelClient(responses=[])
        warmed = run(tmp_path, warm, config=config, run_id="20260907T090000Z-bbbb")

        scrub(tmp_path)
        again = FakeModelClient(responses=list(responses))
        run(tmp_path, again, config=config, run_id="20260908T090000Z-cccc")

        assert cold.call_count == 4
        assert warm.call_count == 0
        assert warmed.cache_hits == 4
        assert again.call_count == 4

    def test_deleting_the_cache_between_two_stages_still_completes(self, tmp_path: Path):
        """Example 3: the one where the cache vanishes mid-run.

        `verify` reads what `extract` produced. That value is held in memory for
        the run, not fetched back out of the cache, so a cache that disappears
        underneath cannot strand the second stage.
        """
        config = pipeline(("extract", "documents"), ("verify", "previous"))

        class Scrubbing(FakeModelClient):
            def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
                if self.call_count == 2:
                    scrub(tmp_path)
                return super().complete(prompt, schema=schema)

        model = Scrubbing(responses=[answer(key) for key in ["INC-4821", "INC-4822"] * 2])
        report = run(tmp_path, model, config=config, run_id="20260806T142203Z-4f1a")

        assert report.failed == []
        assert [step.step for step in report.steps] == ["extract", "verify"]
        assert all(result.records for step in report.steps for result in step.results)

    def test_deleting_the_snapshot_store_is_not_this_rule(self, tmp_path: Path):
        """Counter-example (row 4): the one where deletion is *not* recoverable.

        Snapshots are inputs, not cache. Losing them is unrecoverable without a
        re-sync (R0.2), and the store lives outside the cache directory precisely
        so that clearing the cache cannot take them with it.
        """
        config = pipeline(("extract", "documents"))
        run(
            tmp_path,
            FakeModelClient(responses=[answer(key) for key in ["INC-4821", "INC-4822"]]),
            config=config,
            run_id="20260806T142203Z-4f1a",
        )
        snapshots = tmp_path / ".dossier" / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        (snapshots / "marker").write_bytes(b"a snapshot")

        scrub(tmp_path)

        assert (snapshots / "marker").read_bytes() == b"a snapshot"
        assert not (tmp_path / ".dossier" / "cache").exists()


class TestADamagedEntryIsNotAuthority:
    """R5.9 — the cache is an optimisation and never a source of truth.

    The rule as written covers *deletion*, which correctly misses and recomputes.
    `/quality` found the neighbouring case the spec does not name: an entry that
    is present and unreadable. `payload.decode()` and `model_validate_json` were
    unguarded, and pydantic's `ValidationError` subclasses `ValueError` — so a
    truncated or hand-edited entry propagated out of `execute` and was caught by
    the CLI's resolution handler, which printed "Resolution failed, so nothing ran
    and nothing was written" *after* the manifest was written and earlier stages
    had run.

    Both halves are wrong. A corrupt entry was treated as authority — the one
    thing R5.9's sentence forbids — and the failure was reported as something it
    was not.

    The right answer differs by caller, which is why it is a decision rather than
    a `try` block. For `execute` an unreadable entry is a miss: the work can be
    redone. For `replay` it is fatal: there is nothing to fall back to, and
    recomputing would be the substitution R4.7 row 4 forbids.
    """

    def _damage_every_entry(self, workspace: Path) -> None:
        for entry in (workspace / ".dossier" / "cache" / "stage").rglob("*"):
            if entry.is_file() and not entry.name.endswith(".meta.json"):
                entry.write_bytes(b'{"document": "INC-4821", "fields": [')

    def test_execute_treats_an_unreadable_entry_as_a_miss(self, tmp_path: Path):
        """The one where the work can simply be redone.

        The model is asked again and the answer replaces the damaged bytes. A
        run that aborted here would make one corrupt file permanently fatal to a
        workspace whose inputs are all still present.
        """
        config = pipeline(("extract", "documents"))
        run(
            tmp_path,
            FakeModelClient(responses=[answer(k) for k in DOCUMENTS]),
            config=config,
            run_id="20260806T142203Z-4f1a",
        )
        self._damage_every_entry(tmp_path)

        model = FakeModelClient(responses=[answer(k) for k in DOCUMENTS])
        report = run(tmp_path, model, config=config, run_id="20260907T090000Z-bbbb")

        assert model.call_count == len(DOCUMENTS), "recomputed rather than served"
        assert report.failed == []
        assert report.cache_hits == 0

    def test_a_repaired_entry_is_served_again(self, tmp_path: Path):
        """The one where the damage heals rather than lingering.

        A miss that did not rewrite the entry would leave the workspace paying
        for the same recomputation on every subsequent run.
        """
        config = pipeline(("extract", "documents"))
        run(
            tmp_path,
            FakeModelClient(responses=[answer(k) for k in DOCUMENTS]),
            config=config,
            run_id="20260806T142203Z-4f1a",
        )
        self._damage_every_entry(tmp_path)
        run(
            tmp_path,
            FakeModelClient(responses=[answer(k) for k in DOCUMENTS]),
            config=config,
            run_id="20260907T090000Z-bbbb",
        )

        model = FakeModelClient(responses=[])
        third = run(tmp_path, model, config=config, run_id="20260908T090000Z-cccc")

        assert model.call_count == 0
        assert third.cache_hits == len(DOCUMENTS)

    def test_a_replay_refuses_an_unreadable_entry(self, tmp_path: Path):
        """The counter-example: the caller with nothing to fall back on.

        A replay cannot recompute -- it has no model and, by design, nowhere to
        put one. Serving damaged bytes would be presenting something other than
        what the run produced, and recomputing would be the substitution R4.7
        row 4 forbids. So it stops, and says which entry.
        """
        from dossier.application.manifest import Manifest
        from dossier.application.run import MissingFromReplay, replay

        config = pipeline(("extract", "documents"))
        run(
            tmp_path,
            FakeModelClient(responses=[answer(k) for k in DOCUMENTS]),
            config=config,
            run_id="20260806T142203Z-4f1a",
        )
        manifest = Manifest.read(tmp_path / "runs" / "20260806T142203Z-4f1a" / "manifest.json")
        self._damage_every_entry(tmp_path)

        with pytest.raises(MissingFromReplay) as error:
            replay(
                manifest=manifest,
                document_text=TEXT,
                cache=ArtifactCache(tmp_path, namespace="stage"),
            )

        assert "extract" in str(error.value)
