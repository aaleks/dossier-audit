"""R10.24 — every trace a command opened is looked for on the server as its record
closes, and one the server does not hold is lost.

Against MLflow no trace call reaches the server: the exporter sends a trace
after it ends, on a thread of its own, so a trace the server refuses raises in no
call dossier makes. R10.6 counted none of them. Found live during R10.22, when a
READ-only account's run said nothing about traces while the server logged
`POST /api/3.0/mlflow/traces 403`.

The CLI is handed an `ExporterRefused` through the `build_tracker` seam: a
`FakeTracker` every call of which lands, standing in for `MlflowTracker` as the
record closes. What the tracker found missing is `unrecorded_traces` -- the place
of each trace among those the run opened, never an id a server handed back, so
nothing read from MLflow reaches a run (R0.10).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.fakes import (
    FakePromptRegistry,
    FakeTracker,
    FakeVersionRegistry,
    register_connector,
)
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
TRACES = re.compile(r"^warning: (\d+) trace\(s\) could not be recorded$", re.MULTILINE)
RECORDS = re.compile(r"^warning: (\d+) record\(s\) could not be recorded$", re.MULTILINE)


class ExporterRefused(FakeTracker):
    """Every call lands; the server holds only the traces not in `refused`.

    What `MlflowTracker` knows once it has flushed the exporter and looked the
    run's traces up, said the way it says it: by place, as the record closes.
    """

    def __init__(self, refused: frozenset[int] = frozenset()) -> None:
        super().__init__()
        self._refused = refused
        self.unrecorded_traces: frozenset[int] = frozenset()

    def end_run(self, *, status) -> None:
        super().end_run(status=status)
        self.unrecorded_traces = self._refused


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """The four incidents held, before tracking is switched on."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return workspace


def _tracked_run(workspace: Path, monkeypatch, tracker: FakeTracker):
    import dossier.cli.main as cli

    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(cli, "build_version_registry", lambda settings: FakeVersionRegistry())
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: FakePromptRegistry(), raising=False
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    return _cli(workspace, monkeypatch, "run", PIPELINE)


class TestARunSaysHowManyTracesMlflowNeverReceived:
    """R10.24 — a trace the server does not hold is lost, and said."""

    def test_two_traces_the_exporter_could_not_send_are_said(self, synced: Path, monkeypatch):
        """Example 1: the one where the second and third traces were refused.

        Every call the run made returned, so R10.6 alone counted nothing. The two
        are said as traces and counted as records (R10.21), and the run exits as
        it would have untracked.
        """
        tracker = ExporterRefused(refused=frozenset({1, 2}))

        result = _tracked_run(synced, monkeypatch, tracker)

        assert result.exit_code == 0, result.output
        assert len(tracker.traces) == 4, "all four traces were opened and ended"
        assert TRACES.findall(result.output) == ["2"], result.output
        assert RECORDS.findall(result.output) == ["2"], result.output

    def test_a_server_that_holds_every_trace_says_nothing(self, synced: Path, monkeypatch):
        """Counter-example 6: the one where all four arrived."""
        result = _tracked_run(synced, monkeypatch, ExporterRefused())

        assert result.exit_code == 0, result.output
        assert "could not be recorded" not in result.output
