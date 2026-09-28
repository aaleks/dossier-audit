"""R14.7 — a run links the prompt version each step rendered.

The outer loop for the second half of spec 014, and what the publishing was
for: opening a run in MLflow and reading the words that produced it, rather
than carrying an eight-character hash to a git log.

The version is found by the hash the run already computed, not by what is
newest. A prompt edited and republished between two runs is the case the whole
feature exists for, and a link to the newest version would attach the wrong
words to the older run -- confidently, and with nothing to notice it by.

A real run, not `--plan`: a plan renders no prompt and so links nothing, which
is row 4 rather than an oversight.
"""

from __future__ import annotations

from pathlib import Path

import pytest
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

URI = "http://localhost:5000"
PROMPT = f"{PIPELINE}.extract"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def declared(workspace: Path, monkeypatch) -> Path:
    """The scoring example's incidents, synced and ready to run."""
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
def wired(declared: Path, monkeypatch):
    """Tracking on, a prompt registry that counts, and a model that answers."""
    import dossier.cli.bootstrap as cli

    registry = FakePromptRegistry()
    tracker = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: registry, raising=False
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    return registry, tracker


def _edit_prompt(workspace: Path) -> str:
    prompt = workspace / "pipelines" / PIPELINE / "prompts" / "extract.md"
    original = prompt.read_text(encoding="utf-8")
    prompt.write_text(original + "\nBe precise.\n", encoding="utf-8")
    return original


class TestARunLinksThePromptVersionsItRendered:
    """R14.7 — a run's record links the prompt version each step rendered."""

    def test_a_run_links_the_version_carrying_the_hash_it_rendered(
        self, declared: Path, monkeypatch, wired
    ):
        """Row 1: the one where the newest version is the wrong answer.

        Published, edited, published again, then reverted and run. Two versions
        exist and the run rendered the first, so the first is what its record
        links -- a statement about what ran, not about what is current.
        """
        registry, tracker = wired
        assert _cli(declared, monkeypatch, "prompts", "publish", PIPELINE).exit_code == 0
        original = _edit_prompt(declared)
        assert _cli(declared, monkeypatch, "prompts", "publish", PIPELINE).exit_code == 0
        (declared / "pipelines" / PIPELINE / "prompts" / "extract.md").write_text(
            original, encoding="utf-8"
        )

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert registry.prompts[PROMPT].version == 2, "two versions were published"
        assert (PROMPT, 1) in tracker.links, (
            "the run rendered the first text, so it links version 1 and not the newest"
        )

    def test_a_prompt_that_was_never_published_links_nothing(
        self, declared: Path, monkeypatch, wired
    ):
        """Row 2: the one where the registry has never heard of this prompt.

        Nothing to link to, so nothing is linked -- and the run records and
        exits exactly as it would have. A feature that made a run fail because
        someone had not published its prompts would be tracking changing a run,
        which R10.4 forbids outright.
        """
        registry, tracker = wired

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert tracker.links == [], "nothing published, so nothing linked"

    def test_tracking_off_asks_the_registry_nothing(self, declared: Path, monkeypatch, wired):
        """Counter-example (row 3): the one where the whole mechanism is absent.

        Not merely "links nothing": the registry is never asked. A read that
        happened anyway would be a run reaching a server it was told not to use.
        """
        registry, _ = wired
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "false")

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert registry.reads == [], "tracking off asks the registry nothing"
