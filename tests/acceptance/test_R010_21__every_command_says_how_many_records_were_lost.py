"""R10.21 — every command that records says how many of its records were lost.

R10.6 counted lost traces, and only `dossier run` has traces. A sync whose every
record was refused printed a clean terminal and exited 0, and a person who then
found nothing in MLflow had nothing to go on. A lost record is still not a lost
run (R10.6); this only makes the loss visible.

The CLI is handed a `SilentServer` through the `build_tracker` seam: a
`FakeTracker` whose server stopped answering after the startup check, so every
call raises. Every command that records builds its tracker in `_tracking_for`
and closes its record with `end_run`, which is where the count is said -- so
sync, run, convert and eval here stand for compare and calibrate too, which take
the same path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.fakes import (
    FakePromptRegistry,
    FakeTracker,
    FakeVersionRegistry,
    NoModelClient,
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

pytestmark = pytest.mark.outer_loop

URI = "http://localhost:5000"
GOLD = "gold/incidents"
LOST = re.compile(r"^warning: (\d+) record\(s\) could not be recorded$", re.MULTILINE)


class SilentServer(FakeTracker):
    """A tracker whose server stopped answering after the startup check."""

    def __getattribute__(self, name: str):
        attribute = super().__getattribute__(name)
        if callable(attribute) and not name.startswith("_") and name in _PORT:

            def refused(*args, **kwargs):
                raise ConnectionError(f"the MLflow server at {URI} stopped answering")

            return refused
        return attribute


_PORT = {
    "start_run",
    "log_params",
    "log_metrics",
    "assess",
    "describe",
    "produced_version",
    "rendered_prompt",
    "scored_version",
    "version_prompt",
    "log_version_metrics",
    "log_artifact",
    "log_dataset",
    "start_trace",
    "span",
    "end_trace",
    "end_run",
}


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def held(workspace: Path, monkeypatch) -> Path:
    """The four incidents synced, and a run to score, with tracking still off."""
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
    return workspace


def _tracking(monkeypatch, tracker: FakeTracker) -> None:
    import dossier.cli.main as cli

    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(cli, "build_version_registry", lambda settings: FakeVersionRegistry())
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: FakePromptRegistry(), raising=False
    )


class TestEveryCommandSaysHowManyRecordsWereLost:
    """R10.21 — every command that records says how many of its records were lost."""

    def test_a_sync_whose_every_record_was_lost_says_six(self, held: Path, monkeypatch):
        """Example 1: the one where the server stops answering after the startup check.

        Six records: the run, its params, its metrics, `changes.json`, its
        description and its close. The sync itself completes as it would untracked.
        """
        _tracking(monkeypatch, SilentServer())

        result = _cli(held, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "ledger updated" in result.output
        assert LOST.findall(result.output) == ["6"]

    def test_a_run_says_its_records_and_its_traces(self, held: Path, monkeypatch):
        """Example 2: the record count, and R10.6 row 1's trace count beside it."""
        _tracking(monkeypatch, SilentServer())

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert len(LOST.findall(result.output)) == 1
        assert "trace(s) could not be recorded" in result.output

    @pytest.mark.parametrize(
        "command",
        [("convert", PIPELINE), ("eval", PIPELINE, "--gold", GOLD)],
        ids=["convert", "eval"],
    )
    def test_every_other_command_that_records_says_it_too(
        self, held: Path, monkeypatch, command
    ):
        """Example 3: the same line, from a command with no traces to count."""
        import dossier.cli.main as cli

        _tracking(monkeypatch, SilentServer())
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _cli(held, monkeypatch, *command)

        assert len(LOST.findall(result.output)) == 1, result.output

    def test_nothing_lost_says_nothing(self, held: Path, monkeypatch):
        """Counter-example 4: no line at all -- `0 record(s)` is not printed."""
        _tracking(monkeypatch, FakeTracker())

        result = _cli(held, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "could not be recorded" not in result.output
