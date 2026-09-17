"""R4.12 — `--plan` reports a step as re-running exactly when a run would miss
its cache. The CLI half.

The decision is proved in the unit test beside this one. This one proves the
command is handed the same hashes a run keys on: before this rule `build_plan`
resolved without them, so a prompt edit printed `cached` under `--plan` and
missed under `run` -- one answer arrived at two ways. The previous run here is
a real `dossier run`, not a fabricated manifest, for the same reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import NoModelClient, register_connector
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


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def ran(workspace: Path, monkeypatch) -> Path:
    """The four incidents synced and run once, so there is a manifest to plan against."""
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    # A plan asks no model (R4.6); a call here would be a finding, not a cost.
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return workspace


def _plan(workspace: Path, monkeypatch) -> str:
    result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")
    assert result.exit_code == 0, result.output
    return result.output


class TestPlanSaysPromptChanged:
    """R4.12 — the plan is keyed as the run is, from the same files."""

    def test_an_edited_prompt_is_reported_as_prompt_changed(self, ran: Path, monkeypatch):
        """Example 1: the one where the prompt was edited after a real run.

        The status a run would act on, from the same file the run reads.
        """
        prompt = ran / "pipelines" / PIPELINE / "prompts" / "extract.md"
        prompt.write_text(
            "Read carefully.\n" + prompt.read_text(encoding="utf-8"), encoding="utf-8"
        )

        output = _plan(ran, monkeypatch)

        assert "extract: prompt changed" in output, output

    def test_an_untouched_pipeline_is_cached_throughout(self, ran: Path, monkeypatch):
        """Example 3's shape at the CLI: the one where nothing was edited.

        The plan compared against a real run's manifest, with nothing changed,
        must promise the run will serve everything -- which is only true if the
        plan carried the same hashes the run wrote.
        """
        output = _plan(ran, monkeypatch)

        assert "extract: cached" in output, output
        assert "prompt changed" not in output
