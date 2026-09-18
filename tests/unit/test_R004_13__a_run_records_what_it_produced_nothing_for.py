"""R4.13 — a run that finishes records the documents it produced nothing for.

A failed document is a recorded failure rather than a computed artifact, so
nothing is cached for it (R6.1). Without this record a replay cannot tell that
from a workspace that has lost what a run did produce, and the two want opposite
treatment: reproduce the failure, or refuse by key (R4.7).

Written beside the manifest rather than into it, because the manifest is written
before the first stage runs (R4.1) and a run killed halfway must not leave one
claiming nothing failed. So the file's absence is the safe answer, and the last
row below is that claim.

The rows are the rule's example table, transcribed.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.manifest import OUTCOME_NAME, Outcome
from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

RUN_ID = "20260806T142203Z-4f1a"
STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
SNAPSHOT = "a3f9c1e2" * 8

DOCUMENTS = {"INC-4821": SNAPSHOT, "INC-5044": "c4a70b93" * 8}
# Two documents with *different* text, which matters more than it looks: a stage
# key covers the hash of what it reads and not the document's name (spec 005), so
# two documents with identical text share one key and the second is served from
# the first's answer. Identical text here would test the cache, not the run.
TEXT = {
    "INC-4821": STAGE_INPUTS["INC-4821"],
    "INC-5044": STAGE_INPUTS["INC-4821"] + "The terminals were offline for 77 minutes.\n",
}


def valid_for(document: str) -> str:
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
                id="extract", prompt="prompts/01_extract.md", input="documents", mode="per_file"
            )
        ],
    )


def run(workspace: Path, model, documents=None):
    config = pipeline()
    return execute(
        workspace=workspace,
        pipeline=config,
        pipeline_hash=PIPELINE_HASH,
        documents=DOCUMENTS if documents is None else documents,
        document_text=TEXT,
        schemas={"extract": SCHEMA},
        prompts={step.id: prompt_for(step.inputs) for step in config.steps},
        cache=ArtifactCache(workspace, namespace="stage"),
        model=model,
        run_id=RUN_ID,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


def outcome(workspace: Path) -> Outcome | None:
    return Outcome.read(workspace / "runs" / RUN_ID)


class TestARunRecordsWhatItProducedNothingFor:
    """R4.13 — what a finished run could not produce is a fact, and is written down."""

    def test_a_failed_document_is_named_with_its_step_and_its_error(self, tmp_path: Path):
        """Example 1: the one where `extract` failed on `INC-5044` after both attempts.

        Documents are planned in key order, so `INC-4821` is asked first and
        answers; `INC-5044` is asked twice -- the answer and its correction --
        and never produces the declared shape (R6.2).
        """
        model = FakeModelClient(
            responses=[valid_for("INC-4821"), "not json at all", "still not json"]
        )

        report = run(tmp_path, model)

        assert report.failed == [("extract", "INC-5044")]
        recorded = outcome(tmp_path)
        assert recorded is not None
        assert [(f.step, f.document) for f in recorded.failed] == [("extract", "INC-5044")]
        assert recorded.failed[0].error, "the error the stage gave, not just that it failed"

    def test_a_run_where_everything_produced_output_records_an_empty_list(self, tmp_path: Path):
        """Example 2: the one where nothing failed.

        The file is still written. Its existence is the claim that the run
        reached the end -- which is what lets a replay read its absence as "this
        run said nothing", rather than as "this run had no failures".
        """
        model = FakeModelClient(responses=[valid_for("INC-4821"), valid_for("INC-5044")])

        run(tmp_path, model)

        recorded = outcome(tmp_path)
        assert recorded is not None
        assert recorded.failed == ()
        assert (tmp_path / "runs" / RUN_ID / OUTCOME_NAME).is_file()

    def test_every_failure_is_named_rather_than_counted(self, tmp_path: Path):
        """Example 3: the one where more than one document failed.

        "2 failed" is not something anyone can act on, and two entries naming
        their own step and document are (R6.9).
        """
        model = FakeModelClient(responses=["no", "no", "nor this", "nor this"])

        run(tmp_path, model)

        recorded = outcome(tmp_path)
        assert recorded is not None
        assert sorted(f.document for f in recorded.failed) == ["INC-4821", "INC-5044"]

    def test_a_run_that_did_not_finish_records_nothing(self, tmp_path: Path):
        """Counter-example (row 4): the one killed between two documents.

        The manifest is there, because it is written before the first stage
        (R4.1). The outcome is not, so nothing is claimed about what the run
        produced -- and a replay refuses its missing entries by key (R4.7 row 6).
        """

        class Interrupted(FakeModelClient):
            def complete(self, prompt: str, *, schema: dict | None = None) -> str:
                raise KeyboardInterrupt

        with contextlib.suppress(KeyboardInterrupt):
            run(tmp_path, Interrupted())

        assert (tmp_path / "runs" / RUN_ID / "manifest.json").is_file()
        assert outcome(tmp_path) is None

    def test_a_document_that_never_entered_the_plan_is_absent(self, tmp_path: Path):
        """Counter-example (row 5): the one no installed converter could read.

        A document that failed to convert is not in the manifest, so it is not in
        this record either. It was reported when the run happened (R8.6), and
        claiming it here would report one failure twice in two vocabularies.
        """
        model = FakeModelClient(responses=[valid_for("INC-4821")])

        run(tmp_path, model, documents={"INC-4821": SNAPSHOT})

        recorded = outcome(tmp_path)
        assert recorded is not None
        assert recorded.failed == ()
        assert "audit-note.pdf" not in recorded.model_dump_json()
