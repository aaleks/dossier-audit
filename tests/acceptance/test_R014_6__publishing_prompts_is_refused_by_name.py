"""R14.6 — publishing with tracking off is refused by name before anything is sent.

A machine's configuration, refused where R12.5 and R10.5 refuse theirs: at
startup, naming the thing to fix. Unlike a run, this command has nothing to do
with tracking off -- its whole output is the record -- so off is a refusal
rather than a quiet no-op.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakePromptRegistry
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def registry(workspace: Path, monkeypatch) -> FakePromptRegistry:
    import dossier.cli.bootstrap as cli

    holder = FakePromptRegistry()
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: holder, raising=False
    )
    write_pipeline(workspace, steps=["verify"])
    return holder


class TestPublishingPromptsIsRefusedByName:
    """R14.6 — tracking off, or a server with no prompt registry, is refused by name."""

    def test_tracking_off_refuses_naming_the_variable(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Row 1: the one where the switch is off and the command is pointless.

        Named so the fix is the next thing a person types. Nothing is sent, and
        nothing is half-sent: the refusal is before the first request.
        """
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "false")

        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "DOSSIER_MLFLOW_ENABLED" in result.output
        assert registry.publishes == [], "nothing sent"

    def test_a_run_against_the_same_machine_is_unaffected(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Counter-example (row 5): the one where a command publishing nothing does not care.

        `dossier run --plan` reads the same pipeline on the same machine with
        tracking off and does not refuse. Publishing needs a registry; running
        does not, and R10.4 says tracking may not change what a run does.
        """
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "false")

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert registry.publishes == [], "a run publishes no prompt"
