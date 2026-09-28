"""R10.22 — the first record a server refuses is reported as it is refused.

A 401 or a 403 is not a server going away. It is configuration a person can fix,
and on `dossier run` the report comes before the first model call. It is printed
once; every refusal after it is in R10.21's count, and none of them changes the
outcome (R10.6).

What MLflow raises was read off a live `mlflow server --app-name basic-auth`: an
account holding MLflow's default READ, creating a run in an experiment another
account made, gets `MlflowException` with `PERMISSION_DENIED`, which is HTTP 403.
The tracker here raises that same exception, from MLflow's own class.
"""

from __future__ import annotations

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

pytest.importorskip("mlflow")

URI = "https://mlflow.example.internal"
PASSWORD = "correct-horse-battery-staple"
REFUSED = "MLflow refused a record"


def _raising(error_code: str):
    from mlflow.exceptions import MlflowException
    from mlflow.protos import databricks_pb2

    def refuse(*args, **kwargs):
        raise MlflowException(
            "API request to endpoint /api/2.0/mlflow/runs/create failed with error code "
            "403 != 200. Response body: 'Permission denied'",
            error_code=getattr(databricks_pb2, error_code),
        )

    return refuse


class ReadOnly(FakeTracker):
    """`dossier-ci` holding READ: every write is refused by the server."""

    def __init__(self, error_code: str = "PERMISSION_DENIED") -> None:
        super().__init__()
        self.error_code = error_code

    def __getattribute__(self, name: str):
        if name in _WRITES:
            return _raising(super().__getattribute__("error_code"))
        return super().__getattribute__(name)


class StoppedAnswering(FakeTracker):
    """A server that went away after the startup check."""

    def __getattribute__(self, name: str):
        if name in _WRITES:

            def gone(*args, **kwargs):
                raise ConnectionError(f"the MLflow server at {URI} stopped answering")

            return gone
        return super().__getattribute__(name)


_WRITES = {
    "start_run",
    "log_params",
    "log_metrics",
    "describe",
    "log_artifact",
    "start_trace",
    "span",
    "end_trace",
    "end_run",
    "produced_version",
    "rendered_prompt",
}


class Ordered(RoutedModel):
    """The scoring example's model, noting in `events` when it is first asked."""

    def __init__(self, events: list[str]) -> None:
        super().__init__(ANSWERS)
        self.events = events

    def complete(self, *args, **kwargs):
        if "model" not in self.events:
            self.events.append("model")
        return super().complete(*args, **kwargs)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def held(workspace: Path, monkeypatch) -> Path:
    """The four incidents synced with tracking off."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return workspace


def _as_dossier_ci(monkeypatch, tracker: FakeTracker) -> list[str]:
    """Tracking on as `dossier-ci`; what is warned, and when the model is first asked."""
    import dossier.cli.bootstrap as cli

    events: list[str] = []
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setenv("DOSSIER_MLFLOW_AUTH", "basic")
    monkeypatch.setenv("DOSSIER_MLFLOW_AUTH_USERNAME", "dossier-ci")
    monkeypatch.setenv("DOSSIER_MLFLOW_AUTH_PASSWORD", PASSWORD)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(cli, "build_version_registry", lambda settings: FakeVersionRegistry())
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: FakePromptRegistry(), raising=False
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Ordered(events))
    said = cli._warn

    def noted(line: str) -> None:
        events.append(line)
        said(line)

    monkeypatch.setattr(cli, "_warn", noted)
    return events


class TestARefusedWriteIsReportedBeforeTheWork:
    """R10.22 — the first refused record, reported as it is refused."""

    def test_a_read_only_account_is_told_before_the_first_model_call(
        self, held: Path, monkeypatch
    ):
        """Example 1: the one where `create_run` answers 403.

        Also row 5: the warning holds no password.
        """
        events = _as_dossier_ci(monkeypatch, ReadOnly())

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        refused = [line for line in events if REFUSED in line]
        assert refused, result.output
        assert events.index(refused[0]) < events.index("model"), events
        assert "403" in refused[0]
        assert "dossier-audit/incident-audit/run" in refused[0]
        assert "DOSSIER_MLFLOW_AUTH_USERNAME" in refused[0]
        assert PASSWORD not in result.output

    def test_it_is_said_once_and_the_rest_are_counted(self, held: Path, monkeypatch):
        """Example 2: every record after it refused as well."""
        _as_dossier_ci(monkeypatch, ReadOnly())

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.output.count(REFUSED) == 1, result.output
        assert "record(s) could not be recorded" in result.output

    def test_a_sync_says_it_when_it_opens_its_record(self, held: Path, monkeypatch):
        """Example 3: after the work, because a sync records what it did once done."""
        _as_dossier_ci(monkeypatch, ReadOnly())

        result = _cli(held, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert result.output.count(REFUSED) == 1, result.output

    def test_a_server_that_went_away_is_only_counted(self, held: Path, monkeypatch):
        """Counter-example 4: nothing a person can fix from the terminal, so no warning now."""
        _as_dossier_ci(monkeypatch, StoppedAnswering())

        result = _cli(held, monkeypatch, "sync", PIPELINE)

        assert REFUSED not in result.output
        assert "record(s) could not be recorded" in result.output
