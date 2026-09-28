"""R5.5 — a cache hit produces byte-identical output to the run that populated it.

The whole value of the cache rests on this. A hit that produced *nearly* the same
answer would make every incremental run subtly different from the full run it
claims to stand in for, and the difference would show up as an unexplained score
movement weeks later.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient, NoModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import RunInputs, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

RUN_ID = "20260806T142203Z-4f1a"
STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8}
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)


def answer(document: str = "INC-4821") -> str:
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


def pipeline(**inputs: str) -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(id=name, prompt=f"prompts/{name}.md", input=value, mode="per_file")
            for name, value in inputs.items()
        ],
    )


def run(workspace: Path, model, *, config=None, run_id: str = RUN_ID, documents=None):
    config = config or pipeline(extract="documents")
    return execute(
        RunInputs(
            pipeline=config,
            pipeline_hash=PIPELINE_HASH,
            schemas=dict.fromkeys([step.id for step in config.steps], SCHEMA),
            prompts={step.id: prompt_for(step.inputs) for step in config.steps},
            documents=documents or DOCUMENTS,
            document_text=STAGE_INPUTS,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


def artifacts(workspace: Path) -> dict[str, bytes]:
    root = workspace / ".dossier" / "cache" / "stage"
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestACacheHitIsIdentical:
    """R5.5 — the same bytes, and no model call at all."""

    def test_a_second_run_asks_the_model_nothing(self, tmp_path: Path):
        """Example 1: the one where the answer was already known.

        `NoModelClient` on the second run rather than a counted fake: it fails at
        the call site, so a stage that reached the model names itself instead of
        appearing later as a number that should have been zero.
        """
        run(tmp_path, FakeModelClient(responses=[answer()]))
        first = artifacts(tmp_path)

        second = run(tmp_path, NoModelClient(), run_id="20260907T090000Z-bbbb")

        assert artifacts(tmp_path) == first
        assert second.cache_hits == 1

    def test_the_result_a_hit_rebuilds_matches_the_one_that_was_stored(self, tmp_path: Path):
        """Example 1, the part that matters to a caller.

        Identical bytes on disk is not enough on its own -- the caller gets a
        `DocumentResult`, and the grounding checks in it are re-derived on a hit.
        Being pure (R6.4), they must come out the same.
        """
        fresh = run(tmp_path, FakeModelClient(responses=[answer()]))
        cached = run(tmp_path, NoModelClient(), run_id="20260907T090000Z-bbbb")

        before = fresh.steps[0].results[0]
        after = cached.steps[0].results[0]

        assert after.records == before.records
        assert after.checks == before.checks
        assert before.attempts == 1 and after.attempts == 0

    def test_the_provenance_record_is_present_and_identical(self, tmp_path: Path):
        """Example 2: the one where the record travels with the artifact (R0.3).

        `run_id` differs between the two runs and is deliberately not part of the
        key, so the record written by the first run is the one that survives --
        which is correct: it describes the run that actually computed the bytes.
        """
        run(tmp_path, FakeModelClient(responses=[answer()]))
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((tmp_path / ".dossier" / "cache").rglob("*.meta.json"))
        ]
        assert len(records) == 1
        assert records[0]["run_id"] == RUN_ID
        assert records[0]["step"] == "extract"

        run(tmp_path, NoModelClient(), run_id="20260907T090000Z-bbbb")

        after = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((tmp_path / ".dossier" / "cache").rglob("*.meta.json"))
        ]
        assert after == records

    def test_a_cache_populated_elsewhere_is_read_here(self, tmp_path: Path):
        """Example 3: the one where the cache moves between machines.

        Copied wholesale into a workspace that never ran anything, and read
        without a model. Keys contain no path, no clock and nothing about the
        machine (R5.6), so the entry means the same thing in both places.
        """
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        run(elsewhere, FakeModelClient(responses=[answer()]))

        here = tmp_path / "here"
        here.mkdir()
        shutil.copytree(elsewhere / ".dossier" / "cache", here / ".dossier" / "cache")

        report = run(here, NoModelClient(), run_id="20260907T090000Z-cccc")

        assert report.cache_hits == 1
        assert report.steps[0].results[0].records

    def test_a_changed_input_is_not_a_hit_at_all(self, tmp_path: Path):
        """Counter-example (row 4): the one where a different key is a different entry.

        The document's text changes, so the stage's input hash changes, so the
        key changes. Nothing was invalidated -- the old entry is still there and
        still correct for the old input. A cache that overwrote it would lose the
        artifact a past run is pinned to (R4.9).
        """
        run(tmp_path, FakeModelClient(responses=[answer()]))
        before = artifacts(tmp_path)

        moved = dict(STAGE_INPUTS)
        moved["INC-4821"] = STAGE_INPUTS["INC-4821"] + "\n\nAmended 2026-09-08.\n"

        config = pipeline(extract="documents")
        execute(
            RunInputs(
                pipeline=config,
                pipeline_hash=PIPELINE_HASH,
                schemas={"extract": SCHEMA},
                prompts={"extract": prompt_for(["documents"])},
                documents=DOCUMENTS,
                document_text=moved,
            ),
            workspace=tmp_path,
            model=FakeModelClient(responses=[answer()]),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260907T090000Z-dddd",
            started_at=STARTED_AT,
            dossier_version="0.1.0",
        )

        after = artifacts(tmp_path)
        assert before.items() <= after.items(), "the earlier entry is untouched"
        assert len(after) == len(before) + 2, "a new artifact and its record"
