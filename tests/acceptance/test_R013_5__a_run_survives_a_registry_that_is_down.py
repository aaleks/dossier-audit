"""R13.5 - a run whose version cannot be registered is still a run.

`dossier run` fetches nothing, converts nothing and asks no model differently
because MLflow is down. R10.6 already promises that of the tracker; this is the
same promise for the second port on the same code path, and it needed making
separately because this one returns.

The gap is said out loud, as a lost trace is. A Models tab with nothing in it
should not read as a pipeline nobody ever ran.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import FakeTracker, register_connector
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

from dossier.infrastructure.tracking.best_effort import BestEffortVersionRegistry

URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


class Down:
    """A registry whose server has gone away since the startup check."""

    def register(self, *, record, experiment: str):
        raise ConnectionError("no route to host")


@pytest.fixture
def declared(workspace: Path, monkeypatch) -> Path:
    """The scoring example's four incidents, synced and ready to run."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return workspace


@pytest.fixture
def registry_down(declared: Path, monkeypatch) -> None:
    """Tracking on, a tracker that works, and a registry that cannot be reached."""
    import dossier.cli.bootstrap as cli

    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: FakeTracker(), raising=False)
    monkeypatch.setattr(
        cli,
        "build_version_registry",
        lambda settings: BestEffortVersionRegistry(Down()),
        raising=False,
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))


class TestARunSurvivesARegistryThatIsDown:
    """R13.5 - the work completes, and the gap is reported rather than raised."""

    def test_the_run_completes_and_writes_everything_it_would_have(
        self, declared: Path, monkeypatch, registry_down: None
    ):
        """Example 1: the one that is the whole promise.

        Exit 0, a manifest, and every artifact under `runs/`. A registry is not
        on the path that produces answers, so it cannot be on the path that
        fails them (R0.11).
        """
        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        run_id = result.output.split("run ", 1)[1].split(" ", 1)[0].strip()
        manifest = declared / "runs" / run_id / "manifest.json"
        assert manifest.is_file()
        assert json.loads(manifest.read_text(encoding="utf-8"))["plan"]["steps"]
        assert list((declared / "runs" / run_id / "extract").glob("*.json"))

    def test_the_command_says_the_version_was_not_recorded(
        self, declared: Path, monkeypatch, registry_down: None
    ):
        """Example 2: the one where silence would mislead.

        Said, for the reason a lost trace is (R10.6). An empty Models tab and a
        pipeline nobody ran look identical, and only one of them is a problem.
        """
        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "version could not be recorded" in result.output

    def test_tracking_off_says_nothing_because_nothing_was_attempted(
        self, declared: Path, monkeypatch
    ):
        """Counter-example, row 4: the one where there was nothing to lose.

        No registry is built when tracking is off (R10.1), so there is no gap
        to report -- and a warning here would be a record of a failure that
        never happened.
        """
        import dossier.cli.bootstrap as cli

        monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "version could not be recorded" not in result.output
        assert "recorded to MLflow" not in result.output
