"""R14.11 — a comparison's record links the rubric version both its sides were judged with.

R14.9 for the other command that judges. A comparison's record holds the delta
the change gate exists to produce (R11.8), the figure most likely to be quoted,
and both its sides are judged with the one rubric in the checkout -- so it links
that rubric once, found by its hash rather than by being newest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakePromptRegistry, FakeTracker
from tests.scoring_example import PIPELINE

pytestmark = pytest.mark.outer_loop

RUBRIC = f"{PIPELINE}.judge.root_cause"


@pytest.fixture
def wired(two_runs, monkeypatch) -> tuple[FakePromptRegistry, FakeTracker]:
    """Tracking switched on after both runs, a registry that counts, a tracker that keeps links."""
    import dossier.cli.main as cli

    registry, tracker = FakePromptRegistry(), FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: registry, raising=False
    )
    return registry, tracker


def _rubric(workspace: Path) -> Path:
    return workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"


def _publish(workspace: Path, monkeypatch) -> None:
    published = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
    assert published.exit_code == 0, published.output


def _compare(workspace: Path, monkeypatch, a: str, b: str):
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b)


def _rubric_links(tracker: FakeTracker) -> list[tuple[str, int]]:
    return [link for link in tracker.links if link[0] == RUBRIC]


class TestAComparisonLinksTheRubricItJudgedWith:
    """R14.11 — a comparison links the rubric both its sides were judged with."""

    def test_a_comparison_links_the_version_carrying_its_rubric_once(
        self, two_runs, monkeypatch, wired
    ):
        """Row 1: the one with two sides, one standard, and a newer draft that is neither.

        Once, not once per side: both runs were judged with the checkout's
        rubric. Version 1, not the draft published over it and reverted.
        """
        workspace, a, b = two_runs
        registry, tracker = wired
        _publish(workspace, monkeypatch)
        original = _rubric(workspace).read_text(encoding="utf-8")
        _rubric(workspace).write_text(original + "\nA draft standard.\n", encoding="utf-8")
        _publish(workspace, monkeypatch)
        _rubric(workspace).write_text(original, encoding="utf-8")

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert registry.prompts[RUBRIC].version == 2, "two versions were published"
        assert _rubric_links(tracker) == [(RUBRIC, 1)]

    def test_a_withheld_field_asks_nothing_and_links_nothing(
        self, two_runs, monkeypatch, wired
    ):
        """Counter-example (row 2): the one whose rubric moved since it was measured."""
        workspace, a, b = two_runs
        registry, tracker = wired
        _publish(workspace, monkeypatch)
        _rubric(workspace).write_text(
            _rubric(workspace).read_text(encoding="utf-8") + "\nA new standard.\n",
            encoding="utf-8",
        )
        registry.reads.clear()

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert "stale" in result.output, "the field was withheld, which is the premise"
        assert RUBRIC not in registry.reads
        assert _rubric_links(tracker) == []

    def test_a_rubric_never_published_links_nothing(self, two_runs, monkeypatch, wired):
        """Counter-example (row 3): the one where the registry has never heard of it."""
        workspace, a, b = two_runs
        _, tracker = wired

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert tracker.links == []
        assert len(tracker.runs) == 1, "and the comparison recorded as it always does"

    def test_tracking_off_asks_the_registry_nothing(self, two_runs, monkeypatch, wired):
        """Counter-example (row 4): the one where the whole mechanism is absent."""
        workspace, a, b = two_runs
        registry, _ = wired
        _publish(workspace, monkeypatch)
        registry.reads.clear()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "false")

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert registry.reads == []

    def test_a_refused_comparison_asks_the_registry_nothing(self, two_runs, monkeypatch, wired):
        """Counter-example (row 5): the one with nothing to compare and so no record."""
        workspace, a, b = two_runs
        registry, tracker = wired
        _publish(workspace, monkeypatch)
        registry.reads.clear()
        manifest = workspace / "runs" / b / "manifest.json"
        held = json.loads(manifest.read_text(encoding="utf-8"))
        held["plan"]["documents"] = held["plan"]["documents"][:3]
        manifest.write_text(json.dumps(held, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 2, result.output
        assert registry.reads == []
        assert tracker.links == []
