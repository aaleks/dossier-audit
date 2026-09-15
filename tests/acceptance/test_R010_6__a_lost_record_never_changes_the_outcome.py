"""R10.6 — a record lost after the startup check never changes a command's outcome.

Tracking observes a run; it is never an input to one (R0.10). A tracking server
that stops answering halfway through is a record lost, not a run lost: the work
completes, the answers are cached, and the command exits exactly as it would
have untracked. What changes is one warning saying how much of the record is
missing -- because a silent gap in MLflow would read as documents that were
never processed.

The CLI is handed a `LosingTracker` through the `build_tracker` seam: a
`FakeTracker` whose server stops answering after the second of four traces, so
every call from the third trace on raises. The four incidents are
`_fixtures.md`'s scoring example.
"""

from __future__ import annotations

from pathlib import Path

import httpx
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
WARNING = "warning: 2 trace(s) could not be recorded"


class LosingTracker(FakeTracker):
    """A tracker whose server stops answering after the second of four traces."""

    def __init__(self, answers_traces: int = 2) -> None:
        super().__init__()
        self._answers = answers_traces
        self._started = 0

    def _check(self) -> None:
        if self._started > self._answers:
            raise ConnectionError(f"the MLflow server at {URI} stopped answering")

    def start_trace(self, *, name, tags) -> None:
        self._started += 1
        self._check()
        super().start_trace(name=name, tags=tags)

    def span(self, *, kind, name, attributes) -> None:
        self._check()
        super().span(kind=kind, name=name, attributes=attributes)

    def end_trace(self, *, status, error=None) -> None:
        self._check()
        super().end_trace(status=status, error=error)

    def log_metrics(self, metrics) -> None:
        self._check()
        super().log_metrics(metrics)

    def log_artifact(self, name, content) -> None:
        self._check()
        super().log_artifact(name, content)

    def end_run(self, *, status) -> None:
        self._check()
        super().end_run(status=status)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """The four incidents held, before tracking is switched on."""
    source = IssueTracker(ISSUES)
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: source)
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    return workspace


def _tracked_run(workspace: Path, monkeypatch, answers):
    """`dossier run` with tracking on, recording to a server that stops answering."""
    import dossier.cli.main as cli

    recorder = LosingTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(answers))
    return _cli(workspace, monkeypatch, "run", PIPELINE), recorder


class TestALostRecordNeverChangesTheOutcome:
    """R10.6 — a record lost after the startup check never changes a command's outcome."""

    def test_a_server_lost_midway_still_completes_the_run_and_says_so(
        self, synced: Path, monkeypatch
    ):
        """Example 1: the one where the server stops answering after two of four traces.

        The run completes and exits 0. All four answers are cached -- a second
        run, untracked, serves every one of them and asks nothing -- and one
        warning says two traces are missing from the record.
        """
        import dossier.cli.main as cli

        result, recorder = _tracked_run(synced, monkeypatch, ANSWERS)

        assert result.exit_code == 0, result.output
        assert WARNING in result.output
        assert len(recorder.traces) == 2

        monkeypatch.delenv("DOSSIER_MLFLOW_ENABLED")
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
        again = _cli(synced, monkeypatch, "run", PIPELINE)
        assert again.exit_code == 0, again.output
        assert "4 from cache" in again.output

    def test_a_lost_record_neither_raises_nor_masks_a_failed_document(
        self, synced: Path, monkeypatch
    ):
        """Example 2: the one where `INC-4821` also fails validation.

        Exit 1, as without tracking (R6.9): the failure is the document's, and a
        lost record neither causes an exit code nor hides one.
        """
        broken = {**ANSWERS, "INC-4821": [{"not_a_field": True}]}

        result, _ = _tracked_run(synced, monkeypatch, broken)

        assert result.exit_code == 1, result.output
        assert WARNING in result.output

    def test_a_server_down_before_the_command_is_refused_not_warned_about(
        self, synced: Path, monkeypatch
    ):
        """Counter-example (row 3): the one where nothing answers from the start.

        Not this rule: refused before any work by R10.5, with exit 2 -- never
        run and then warned about.
        """
        import dossier.cli.main as cli
        import dossier.infrastructure.tracking.mlflow as adapter

        def refused(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(adapter, "HEALTH_TRANSPORT", httpx.MockTransport(refused))
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2
        assert "could not be recorded" not in result.output
