"""R14.7 — a run links the prompt version each step rendered.

The outer loop for the second half of spec 014, and what the publishing was for:
opening a run in MLflow and reading the words that produced it, rather than
carrying an eight-character hash to a git log.

The version is found by the hash the run already computed, not by what is
newest. A prompt edited and republished between two runs is the case the whole
feature exists for, and a link to the newest version would attach the wrong
words to the older run -- confidently, and with nothing to notice it by.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, FakePromptRegistry, FakeTracker
from tests.pipelines import write_pipeline

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def wired(workspace: Path, monkeypatch):
    """Tracking on, a registry that counts, and a model that never really answers."""
    import dossier.cli.main as cli

    registry = FakePromptRegistry()
    tracker = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_prompt_registry", lambda settings: registry, raising=False)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    write_pipeline(workspace, steps=["extract"], sources=["incidents-manual"])
    return registry, tracker


class TestARunLinksThePromptVersionsItRendered:
    """R14.7 — a run's record links the prompt version each step rendered."""

    def test_a_run_links_the_version_carrying_the_hash_it_rendered(
        self, workspace: Path, monkeypatch, wired
    ):
        """Row 1: the one where the newest version is the wrong answer.

        The prompt is published, then edited, then published again. The run
        rendered the first text, so the first version is what its record links --
        a statement about what ran, not about what is current.
        """
        registry, tracker = wired
        _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
        prompt = workspace / "pipelines" / PIPELINE / "prompts" / "extract.md"
        original = prompt.read_text(encoding="utf-8")
        prompt.write_text(original + "\nSay where you looked.\n", encoding="utf-8")
        _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
        prompt.write_text(original, encoding="utf-8")

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert registry.prompts[f"{PIPELINE}.extract"].version == 2, "two versions published"
        assert tracker.links == [(f"{PIPELINE}.extract", 1)], (
            "the run rendered the first text, so it links version 1 and not the newest"
        )

    def test_a_prompt_that_was_never_published_links_nothing(
        self, workspace: Path, monkeypatch, wired
    ):
        """Row 2: the one where the registry has never heard of this prompt.

        Nothing to link to, so nothing is linked -- and the run records and exits
        exactly as it would have. A feature that made a run fail because someone
        had not published its prompts would be tracking changing a run, which
        R10.4 forbids outright.
        """
        registry, tracker = wired

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert tracker.links == [], "nothing published, so nothing linked"

    def test_tracking_off_reads_the_registry_not_at_all(
        self, workspace: Path, monkeypatch, wired
    ):
        """Counter-example (row 3): the one where the whole mechanism is absent.

        Not merely "links nothing": the registry is never asked. A read that
        happened anyway would be a run reaching a server it was told not to use.
        """
        registry, _ = wired
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "false")

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert registry.reads == [], "tracking off asks the registry nothing"
