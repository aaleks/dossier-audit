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

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import execute
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8, "INC-4822": "77c1b40a" * 8}
SCHEMA = {"type": "object"}

TEXT = {
    key: STAGE_INPUTS["INC-4821"] + f"\n\nFiled as {key}.\n" for key in DOCUMENTS
}


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
    """
    return [
        (step.step, result.document, result.records, result.checks, result.error)
        for step in report.steps
        for result in step.results
    ]


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

        scrub(tmp_path)
        again = run(
            tmp_path,
            FakeModelClient(responses=[answer(key) for key in ["INC-4821", "INC-4822"] * 2]),
            config=config,
            run_id="20260907T090000Z-bbbb",
        )

        assert outputs(again) == outputs(first)

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
            def complete(self, prompt: str, *, schema: dict | None = None) -> str:
                if self.call_count == 2:
                    scrub(tmp_path)
                return super().complete(prompt, schema=schema)

        model = Scrubbing(
            responses=[answer(key) for key in ["INC-4821", "INC-4822"] * 2]
        )
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
