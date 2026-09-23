"""R10.15 — the retired `DOSSIER_MLFLOW_PROMPT_PREFIX` is refused by name.

R10.13 replaced it with one namespace for prompts and datasets. A machine that
still sets it, ignored, would stop being namespaced without a word, and its next
publish would land in the history it was set to keep apart from. Refused, the
message names the one change to make.

Written into the workspace's `.env`, because that is where a machine keeps it:
a variable that only a shell carried would be gone with the shell.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.conftest import URI, _cli
from tests.fakes import FakePromptRegistry, FakeTracker, register_connector
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

RETIRED = "DOSSIER_MLFLOW_PROMPT_PREFIX"
NAMESPACE = "DOSSIER_MLFLOW_NAMESPACE"


@pytest.fixture
def machine(workspace: Path, monkeypatch):
    """A synced workspace with tracking on, whose `.env` still sets the retired variable."""
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

    prompts, tracker, model = FakePromptRegistry(), FakeTracker(), RoutedModel(ANSWERS)
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: prompts, raising=False
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return workspace, prompts, tracker, model


def _dotenv(workspace: Path, value: str) -> None:
    (workspace / ".env").write_text(f"{RETIRED}={value}\n", encoding="utf-8")


def _refused(result) -> None:
    assert result.exit_code == 2, result.output
    assert RETIRED in result.output, "the refusal names the variable that was set"
    assert NAMESPACE in result.output, "and the one that replaced it"


class TestTheRetiredPromptPrefixIsRefusedByName:
    """R10.15 — `DOSSIER_MLFLOW_PROMPT_PREFIX`, set to a value, is refused by name."""

    def test_a_publish_is_refused_before_anything_is_sent(self, machine, monkeypatch):
        """Row 1: the one that would have published into the shared history."""
        workspace, prompts, _, _ = machine
        _dotenv(workspace, "sandbox")

        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        _refused(result)
        assert prompts.publishes == [], "0 prompts sent"

    def test_a_run_is_refused_before_its_record_opens(self, machine, monkeypatch):
        """Row 2: the one that would have linked prompts under the wrong names."""
        workspace, _, tracker, model = machine
        _dotenv(workspace, "sandbox")

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        _refused(result)
        assert model.call_count == 0, "no model call"
        assert tracker.runs == [], "no MLflow run opened"

    def test_a_blank_retired_variable_is_not_a_decision(self, machine, monkeypatch):
        """Counter-example (row 3): the one copied from an old `.env.example`."""
        workspace, prompts, _, _ = machine
        _dotenv(workspace, "")

        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert result.exit_code == 0, result.output
        assert f"{PIPELINE}.extract" in prompts.prompts

    def test_tracking_off_reads_it_not_at_all(self, machine, monkeypatch):
        """Counter-example (row 4): the one where nothing is published or looked up."""
        workspace, _, _, _ = machine
        _dotenv(workspace, "sandbox")
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "false")

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
