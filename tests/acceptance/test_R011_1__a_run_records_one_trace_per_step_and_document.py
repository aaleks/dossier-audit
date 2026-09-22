"""R11.1 — a `dossier run` is one MLflow run, named after its run id, with one
trace per (step, document).

A trace is one (step, document): the unit of a cache key, so one trace is one key
computed or served. Following `INC-4821` through a pipeline is then a filter on
its `dossier.document` tag, and a failed document is a trace with an error
status -- which is what people open MLflow to find (spec 011).

Tracking observes a run and is never an input to one (R0.10). So `--plan` and
`--replay`, which make nothing new, record nothing at all.

Tracking is switched on the way a person would switch it on, in the environment
(R10.1), and the CLI is handed a `FakeTracker` through the same kind of seam as
`build_model_client`: it counts runs, traces and spans and sends nothing
anywhere. The four incidents are `_fixtures.md`'s scoring example.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import FakeTracker, NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _run(workspace: Path, monkeypatch, model) -> tuple[object, str]:
    """`dossier run`, answered by `model`; the result and the run id it printed."""
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    found = re.search(r"^run (\S+)", result.output, re.MULTILINE)
    return result, found.group(1) if found else ""


class ReportingModel(RoutedModel):
    """The scoring example's answers for each document, and prose for an aggregate step.

    An aggregate step reads every document at once, so its prompt names no
    single incident to route by. Detected by counting the wrappers rather than
    by their presence: since R3.13 a `per_file` prompt carries one too, and a
    fake that read presence alone answered prose to every step.
    """

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        if prompt.count('<document key="') > 1:
            self.calls.append("*")
            return "Four incidents; three stated a loss."
        return super().complete(prompt, schema=schema)


@pytest.fixture
def tracker(workspace: Path, monkeypatch) -> FakeTracker:
    """The four incidents held, then tracking switched on and recording to a fake.

    Synced before tracking is on, so the only MLflow run under test is the
    `dossier run` each test makes.
    """
    import dossier.cli.main as cli

    source = IssueTracker(ISSUES)
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: source)
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


class TestARunRecordsOneTracePerStepAndDocument:
    """R11.1 — a `dossier run` is one MLflow run, named after its run id, with one
    trace per (step, document)."""

    def test_a_run_is_one_mlflow_run_named_after_its_run_id_with_a_trace_per_document(
        self, workspace: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where `extract` runs over four documents, nothing cached."""
        result, run_id = _run(workspace, monkeypatch, RoutedModel(ANSWERS))

        assert result.exit_code == 0, result.output
        assert [run.name for run in tracker.runs] == [run_id]
        assert sorted(
            (trace.tags["dossier.step"], trace.tags["dossier.document"])
            for trace in tracker.runs[0].traces
        ) == [("extract", key) for key in sorted(ISSUES)]

    def test_the_run_records_what_it_pinned_what_it_did_and_its_manifest(
        self, workspace: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one read back for its pipeline, model, counts and manifest.

        Every figure is one the run already knows and prints; MLflow is a second
        place to read it, never a second way of computing it (spec 011).
        """
        result, run_id = _run(workspace, monkeypatch, RoutedModel(ANSWERS))

        assert result.exit_code == 0, result.output
        manifest = workspace / "runs" / run_id / "manifest.json"
        plan = json.loads(manifest.read_text(encoding="utf-8"))["plan"]
        run = tracker.runs[0]
        # Per entry rather than as a whole dict. R11.1 claims these three are
        # recorded; it does not claim they are the only params, and R11.18 adds
        # the versions of what produced the run beside them.
        assert run.params["pipeline"] == PIPELINE
        assert run.params["model"] == RoutedModel.model_id
        assert run.params["pipeline_hash"] == plan["pipeline_hash"]
        assert run.metrics == {"documents": 4, "cache_hits": 0, "model_calls": 4, "failed": 0}
        assert run.artifacts["manifest.json"] == manifest.read_bytes()

    def test_an_aggregate_step_is_one_trace_under_document_star(
        self, workspace: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 3: the one with a `report` step that reads every document at once."""
        path = write_pipeline(
            workspace,
            sources=[SOURCE_ID],
            steps=["extract", "report"],
            inputs={"report": "extract"},
            outputs={"report": None},
        )
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "input: extract\n    mode: per_file", "input: extract\n    mode: aggregate"
            ),
            encoding="utf-8",
        )

        result, _ = _run(workspace, monkeypatch, ReportingModel(ANSWERS))

        assert result.exit_code == 0, result.output
        reports = [
            trace.tags["dossier.document"]
            for trace in tracker.runs[0].traces
            if trace.tags["dossier.step"] == "report"
        ]
        assert reports == ["*"]

    def test_a_document_that_failed_is_a_trace_with_an_error_status(
        self, workspace: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 4: the one where `INC-4821` fails validation twice.

        Its trace says ERROR and names the error (R6.9); the three documents
        that succeeded stay OK. The run exits 1, as it would untracked.
        """
        broken = {**ANSWERS, "INC-4821": [{"not_a_field": True}]}

        result, _ = _run(workspace, monkeypatch, RoutedModel(broken))

        assert result.exit_code == 1, result.output
        by_document = {
            trace.tags["dossier.document"]: trace for trace in tracker.runs[0].traces
        }
        assert by_document["INC-4821"].status == "ERROR"
        assert "INC-4821" in (by_document["INC-4821"].error or "")
        assert {
            key: trace.status for key, trace in by_document.items() if key != "INC-4821"
        } == {key: "OK" for key in ISSUES if key != "INC-4821"}

    def test_a_plan_records_nothing(self, workspace: Path, monkeypatch, tracker: FakeTracker):
        """Counter-example (row 5): the one that only reports what would run (R4.6)."""
        import dossier.cli.main as cli

        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert tracker.runs == []
        assert tracker.traces == []

    def test_a_replay_records_nothing(self, workspace: Path, monkeypatch, tracker: FakeTracker):
        """Counter-example (row 6): the one reproducing a past run from its manifest.

        A replay reproduces a record; it does not make one (R4.7). The run it
        replays was recorded once, when it ran, and is not recorded again.
        """
        ran, run_id = _run(workspace, monkeypatch, RoutedModel(ANSWERS))
        assert ran.exit_code == 0, ran.output
        recorded = len(tracker.runs)

        result = _cli(workspace, monkeypatch, "run", "--replay", f"runs/{run_id}/")

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == recorded
