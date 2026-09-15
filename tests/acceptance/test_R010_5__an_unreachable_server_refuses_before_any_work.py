"""R10.5 — with tracking enabled, an unreachable server refuses the command before
any work.

Checked once, at startup. An hour of model calls nobody can inspect afterwards is
the failure this prevents: a person who switched tracking on asked for a record,
and a run that silently made none would be found out only when they went looking
for it.

The MLflow adapter checks its server's `/health` through a transport the test
can answer, as `register_connector` supplies a connector: here it answers with a
connection that never opens, which is what nothing listening at
`http://localhost:5000` looks like. No socket is opened. The four incidents are
`_fixtures.md`'s scoring example.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from tests.fakes import NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

URI = "http://localhost:5000"


class CountingTracker(IssueTracker):
    """The issue-tracker source, counting what it was asked to fetch."""

    def __init__(self, issues) -> None:
        super().__init__(issues)
        self.fetched: list[str] = []

    def fetch(self, key: str):
        self.fetched.append(key)
        return super().fetch(key)


def _refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def source(workspace: Path, monkeypatch) -> CountingTracker:
    """The four incidents as a source, registered and not yet synced."""
    incidents = CountingTracker(ISSUES)
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: incidents)
    return incidents


def _tracking_on(monkeypatch) -> None:
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)


def _server_down(monkeypatch) -> None:
    """Nothing answering at the tracking URI: every connection is refused."""
    import dossier.infrastructure.tracking.mlflow as adapter

    monkeypatch.setattr(adapter, "HEALTH_TRANSPORT", httpx.MockTransport(_refused))


class TestAnUnreachableServerRefusesBeforeAnyWork:
    """R10.5 — with tracking enabled, an unreachable server refuses the command
    before any work."""

    def test_a_run_is_refused_naming_the_uri_before_any_model_call(
        self, workspace: Path, monkeypatch, source: CountingTracker
    ):
        """Example 1: the one where nothing answers at `http://localhost:5000`.

        The documents are held first, with tracking off, so the run has real
        work it could have done -- and does none of it.
        """
        import dossier.cli.main as cli

        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        _tracking_on(monkeypatch)
        _server_down(monkeypatch)
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2
        assert URI in result.output
        assert not (workspace / "runs").exists(), "no run directory"

    def test_a_sync_is_refused_before_any_fetch(
        self, workspace: Path, monkeypatch, source: CountingTracker
    ):
        """Example 2: the one where the same server is down for `dossier sync`.

        Nothing is fetched and the ledger is not touched: refused before any
        work means before the first request to the source, too.
        """
        _tracking_on(monkeypatch)
        _server_down(monkeypatch)
        state = workspace / ".dossier"
        before = sorted(state.rglob("*")) if state.exists() else []

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 2
        assert source.fetched == []
        assert (sorted(state.rglob("*")) if state.exists() else []) == before

    def test_a_missing_tracking_extra_is_refused_naming_it(
        self, workspace: Path, monkeypatch, source: CountingTracker
    ):
        """Example 3: the one switched on without `mlflow` installed.

        Tracking is an optional extra. Asking for it without installing it is
        refused naming what to install, rather than failing on an import deep
        inside a run.
        """
        _tracking_on(monkeypatch)
        monkeypatch.setitem(sys.modules, "mlflow", None)

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 2
        assert "dossier[tracking]" in result.output

    def test_a_plan_needs_no_server(
        self, workspace: Path, monkeypatch, source: CountingTracker
    ):
        """Counter-example (row 4): the one planned while the server is down.

        `--plan` records nothing (R11.1), so it needs no server, and refusing it
        would stop someone checking a pipeline for want of something unused.
        """
        import dossier.cli.main as cli

        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        _tracking_on(monkeypatch)
        _server_down(monkeypatch)
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
