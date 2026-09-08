"""R4.1 — resolution completes fully before any stage executes.

A resolution error means nothing ran, so a half-executed pipeline is never a
state the system can be in.

The two failure modes in this file look alike and are deliberately different. A
resolution failure is a statement about the pipeline: nothing about the run is
well-defined, so nothing happens and no run directory appears. An execution
failure is a statement about one document: everything else is still valid, the
earlier stages keep their results, and the run reports which document failed
(R6.9). Collapsing the two in either direction is the bug this rule prevents --
one way loses work that was correct, the other way ships an audit that quietly
covered less than it claims.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, NoModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS

from dossier.application.run import execute
from dossier.domain.pipeline import PipelineConfig, StepConfig

RUN_ID = "20260806T142203Z-4f1a"
STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8}
SCHEMA = {"type": "object"}


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


def pipeline(**inputs: str) -> PipelineConfig:
    """A pipeline whose steps read what the caller says, in declaration order."""
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(
                id=name, prompt="prompts/01_extract.md", input=value, mode="per_file"
            )
            for name, value in inputs.items()
        ],
    )


def run(workspace: Path, config: PipelineConfig, model, **overrides):
    """Execute a pipeline, with everything this layer refuses to look up itself."""
    arguments = {
        "workspace": workspace,
        "pipeline": config,
        "pipeline_hash": PIPELINE_HASH,
        "documents": DOCUMENTS,
        "document_text": STAGE_INPUTS,
        "schemas": dict.fromkeys([step.id for step in config.steps], SCHEMA),
        "prompt_for": lambda step, document: f"<{step}>{{{{documents}}}}</{step}>",
        "model": model,
        "run_id": RUN_ID,
        "started_at": STARTED_AT,
        "dossier_version": "0.1.0",
    }
    return execute(**{**arguments, **overrides})


class TestResolutionFailureIsTotal:
    """R4.1 — a pipeline that does not resolve does not partially run."""

    def test_an_unknown_reference_names_the_step_and_runs_nothing(self, tmp_path: Path):
        """Example 1: the one where `report` reads a step nobody declared.

        `NoModelClient` rather than a counted fake: it fails at the call site, so
        a stage that ran would name itself in the traceback instead of showing up
        later as a number that should have been zero.
        """
        broken = pipeline(extract="documents", verify="extract", report="enrich")

        with pytest.raises(ValueError) as error:
            run(tmp_path, broken, NoModelClient())

        assert "report" in str(error.value)
        assert "enrich" in str(error.value)

    def test_no_run_directory_is_created(self, tmp_path: Path):
        """Example 2: the one where the failure leaves no trace on disk.

        A `runs/<id>/` holding a manifest for a pipeline that never ran is worse
        than no directory at all -- it is a record of a run that did not happen.
        """
        broken = pipeline(extract="documents", report="enrich")

        with pytest.raises(ValueError):
            run(tmp_path, broken, NoModelClient())

        assert not (tmp_path / "runs").exists()

    def test_a_relative_reference_with_no_predecessor_is_also_total(self, tmp_path: Path):
        """The one where resolution fails on the sugar rather than on an id.

        R4.3's error has to be as total as R3.3's. Both are resolution, and the
        rule is about the phase, not about which check inside it objected.
        """
        broken = pipeline(extract="previous")

        with pytest.raises(ValueError):
            run(tmp_path, broken, NoModelClient())

        assert not (tmp_path / "runs").exists()


class TestTheManifestIsWrittenFirst:
    """R4.1 example 3 — before the first stage is entered, not after the last."""

    def test_the_manifest_exists_by_the_time_a_stage_asks_the_model(self, tmp_path: Path):
        """The one asserted from inside the first model call.

        Checking after the run would pass whether the manifest was written first
        or last. The only moment that distinguishes them is during a stage, so
        the fake looks at the disk when it is called.

        This matters because the manifest is what makes a run reproducible: a run
        interrupted halfway through with no manifest cannot be replayed (R4.7),
        and an interrupted run is the normal case, not the exotic one.
        """
        seen: list[bool] = []
        manifest = tmp_path / "runs" / RUN_ID / "manifest.json"

        class Watching(FakeModelClient):
            def complete(self, prompt: str, *, schema: dict | None = None) -> str:
                seen.append(manifest.is_file())
                return super().complete(prompt, schema=schema)

        run(tmp_path, pipeline(extract="documents"),
            Watching(responses=[valid_for("INC-4821")]))

        assert seen == [True], "the manifest must exist before the first call, not after"

    def test_the_manifest_records_the_run_and_the_resolved_plan(self, tmp_path: Path):
        """The one where the manifest is readable on its own (R4.4).

        Every input is concrete and the run's own identity travels with it, so a
        person opening this file years later needs nothing else.
        """
        report = run(
            tmp_path,
            pipeline(extract="documents", verify="previous"),
            FakeModelClient(responses=[valid_for("INC-4821"), valid_for("INC-4821")]),
        )

        written = json.loads(report.manifest_path.read_text(encoding="utf-8"))

        assert written["run_id"] == RUN_ID
        assert written["plan"]["pipeline"] == "incident-audit"
        assert written["plan"]["steps"][1]["inputs"] == ["extract"]
        assert "previous" not in json.dumps(written)


class TestExecutionFailureIsNotTotal:
    """R4.1 counter-example (row 4) — the other kind of failure, kept apart."""

    def test_an_earlier_stage_keeps_its_results(self, tmp_path: Path):
        """The one where `verify` fails on `INC-4821` and `extract` survives.

        This is the row that stops the rule being implemented as "any error
        aborts everything". Execution failures are per-document (R6.9);
        resolution failures are total. A run that threw away `extract` here would
        discard work that was correct and expensive.
        """
        model = FakeModelClient(responses=[valid_for("INC-4821"), "not json at all",
                                           "still not json"])

        report = run(tmp_path, pipeline(extract="documents", verify="previous"), model)

        extract, verify = report.steps
        assert extract.step == "extract"
        assert [result.failed for result in extract.results] == [False]
        assert [result.failed for result in verify.results] == [True]

    def test_the_run_directory_survives_an_execution_failure(self, tmp_path: Path):
        """The one where a failed document still leaves a reviewable run.

        The opposite of example 2, and deliberately so: here something really did
        happen, and the manifest is how anyone finds out what.
        """
        model = FakeModelClient(responses=["not json", "still not json"])

        report = run(tmp_path, pipeline(extract="documents"), model)

        assert report.manifest_path.is_file()
        assert report.failed == [("extract", "INC-4821")]


class TestAnUnexecutableModeIsAlsoARefusal:
    """R4.1 — "cannot be executed as written" has the same shape as "does not resolve"."""

    def test_an_aggregate_step_is_refused_before_anything_runs(self, tmp_path: Path):
        """The one where a declared mode is not silently reinterpreted.

        `execute` runs every step over every document, which is `per_file`. An
        aggregate step reaching that loop would become one call per document
        instead of one over all of them -- a different question asked of the
        model, a different bill, and an answer that looks entirely normal.

        Refusing during resolution puts it where R4.1 wants it: nothing runs, and
        no run directory appears.
        """
        config = pipeline(extract="documents")
        aggregating = config.model_copy(
            update={"steps": [config.steps[0].model_copy(update={"mode": "aggregate"})]}
        )

        with pytest.raises(ValueError) as error:
            run(tmp_path, aggregating, NoModelClient())

        assert "aggregate" in str(error.value)
        assert "extract" in str(error.value)
        assert not (tmp_path / "runs").exists()
