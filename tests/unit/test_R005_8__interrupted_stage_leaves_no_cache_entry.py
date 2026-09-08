"""R5.8 — an interrupted stage leaves no cache entry.

A partially written artifact is never treated as a hit. Otherwise one interrupted
run poisons every run after it, and the symptom appears far from the cause: a
stage returning truncated JSON, or an artifact nothing can explain, weeks later
and nowhere near the afternoon somebody pressed Ctrl-C.

Two mechanisms carry this, and they are different. Each file is written through a
temporary name and renamed, so a kill *during* a write leaves nothing. And a hit
requires the provenance record as well as the artifact, so a kill *between* the
two writes reads back as a miss.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, FakeModelClientError
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import execute
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

RUN_ID = "20260806T142203Z-4f1a"
STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
SCHEMA = {"type": "object"}
FIVE = ["INC-4821", "INC-4822", "INC-4901", "INC-5044", "INC-5102"]


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


def pipeline() -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(
                id="extract", prompt="prompts/extract.md", input="documents", mode="per_file"
            )
        ],
    )


def run(workspace: Path, model, *, documents, cache=None, run_id: str = RUN_ID):
    return execute(
        workspace=workspace,
        pipeline=pipeline(),
        pipeline_hash=PIPELINE_HASH,
        documents=documents,
        # Distinct text per document, so each is its own stage key. Identical
        # text would make them one computation and four cache hits, which is
        # correct behaviour and not what these rows are about (R5.7 row 4).
        document_text={
            key: STAGE_INPUTS["INC-4821"] + f"\n\nFiled as {key}.\n" for key in documents
        },
        schemas={"extract": SCHEMA},
        prompts={"extract": prompt_for(["documents"])},
        model=model,
        cache=cache or ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


def five_documents() -> dict[str, str]:
    return {key: f"{index:064d}" for index, key in enumerate(FIVE)}


def entries(workspace: Path) -> list[Path]:
    root = workspace / ".dossier" / "cache" / "stage"
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []


class TestAnInterruptionLeavesNothingUsable:
    """R5.8 — a partial write is never a hit."""

    def test_a_kill_during_the_write_leaves_no_file(self, tmp_path: Path):
        """Example 1: the one where the process dies mid-write.

        The write is simulated by making the rename fail after the temporary file
        exists. What must survive is the absence of a truncated artifact at the
        key -- and the absence of the `.part` file it was being written through.
        """
        cache = ArtifactCache(tmp_path, namespace="stage")

        class Interrupted(ArtifactCache):
            def _write(self, destination: Path, payload: bytes) -> None:
                raise KeyboardInterrupt("killed mid-write")

        broken = Interrupted(tmp_path, namespace="stage")
        with pytest.raises(KeyboardInterrupt):
            run(tmp_path, FakeModelClient(responses=[answer("INC-4821")]),
                documents={"INC-4821": "a" * 64}, cache=broken)

        assert entries(tmp_path) == []
        assert cache.get("b" * 64) is None

    def test_no_part_file_is_left_behind(self, tmp_path: Path):
        """The one where the temporary file is cleaned up.

        A `.part` left in the cache directory is not read back as an artifact,
        but it is litter that grows without bound on a flaky machine.
        """
        cache = ArtifactCache(tmp_path, namespace="stage")

        class Failing(ArtifactCache):
            @staticmethod
            def _write(destination: Path, payload: bytes) -> None:
                ArtifactCache._write(destination, payload)
                raise OSError("disk full")

        with pytest.raises(OSError, match="disk full"):
            Failing(tmp_path, namespace="stage").put("c" * 64, b"partial")

        leftovers = [path for path in entries(tmp_path) if path.suffix == ".part"]
        assert leftovers == []
        assert cache.get("c" * 64, require_record=True) is None, (
            "an artifact whose record was never written is not an entry"
        )

    def test_an_artifact_without_its_record_is_a_miss(self, tmp_path: Path):
        """Example 2: the one where the kill lands between the two writes.

        The artifact is on disk and complete. Nothing can say what produced it,
        so it is not a cache entry (R0.3), and the next run recomputes it rather
        than serving bytes it cannot explain.
        """
        cache = ArtifactCache(tmp_path, namespace="stage")
        cache.put("d" * 64, b'{"document":"INC-4821","fields":[]}')

        assert cache.get("d" * 64) is not None, "the artifact really is there"
        assert cache.get("d" * 64, require_record=True) is None

    def test_the_next_run_recomputes_what_it_cannot_explain(self, tmp_path: Path):
        """Example 2, end to end: the model is asked again, and the entry heals."""
        documents = {"INC-4821": "a" * 64}
        run(tmp_path, FakeModelClient(responses=[answer("INC-4821")]), documents=documents)

        for record in (tmp_path / ".dossier" / "cache").rglob("*.meta.json"):
            record.unlink()

        model = FakeModelClient(responses=[answer("INC-4821")])
        report = run(tmp_path, model, documents=documents, run_id="20260907T090000Z-bbbb")

        assert model.call_count == 1, "the orphaned artifact was not served"
        assert report.cache_hits == 0
        assert len(list((tmp_path / ".dossier" / "cache").rglob("*.meta.json"))) == 1

    def test_a_stage_raising_partway_keeps_what_it_finished(self, tmp_path: Path):
        """Example 3: the one where two of five are done when it dies.

        Those two are complete, explained entries and are kept -- re-doing them
        would be the other failure this rule guards against, throwing away work
        that was correct.
        """
        documents = five_documents()
        model = FakeModelClient(responses=[answer(key) for key in FIVE[:2]])

        # Named rather than blind: the fake runs out of scripted responses on the
        # third document, which is what stands in for the process dying. A bare
        # `Exception` would also pass on an unrelated error and prove nothing.
        with pytest.raises(FakeModelClientError):
            run(tmp_path, model, documents=documents)

        artifacts = [path for path in entries(tmp_path) if path.suffix != ".json"]
        records = [path for path in entries(tmp_path) if path.name.endswith(".meta.json")]
        assert len(artifacts) == 2
        assert len(records) == 2

    def test_a_document_that_failed_validation_is_not_cached(self, tmp_path: Path):
        """Counter-example (row 4): the one that is not an interruption at all.

        Two invalid answers is a recorded per-document failure, not a crash. It
        is deliberately not cached: caching it would make one bad afternoon
        permanent, and the next run would never even ask (R6.1, R6.9).
        """
        documents = {"INC-4821": "a" * 64}
        model = FakeModelClient(responses=["not json", "still not json"])

        report = run(tmp_path, model, documents=documents)

        assert report.failed == [("extract", "INC-4821")]
        assert entries(tmp_path) == []
