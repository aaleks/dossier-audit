"""R11.13 — a comparison names the steps that differ between the two runs.

`two_runs` is the comparison example of `_fixtures.md`: the same four documents
run twice, the second after the prompt changed. So the cause this test looks for
in the record is one a person wrote down, not one the test arranged.

The unit test beside this one proves what the line says. This one proves the
comparison computes it from the two manifests it already read, rather than the
delta arriving with no stated cause as it did before.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeTracker
from tests.scoring_example import PIPELINE

CHANGED = "dossier.changed_steps"


@pytest.fixture
def tracker(two_runs: tuple[Path, str, str], monkeypatch) -> FakeTracker:
    """Tracking switched on after both runs, so the only record is the comparison."""
    import dossier.cli.bootstrap as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


class TestCompareNamesWhatChangedBetweenItsRuns:
    """R11.13 — a comparison names the steps that differ between the two runs."""

    def test_the_changed_prompt_is_named_on_the_comparison(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one the change gate is opened to answer.

        Run `b` was made after the prompt changed. The delta and its cause now
        sit on the same record; before this, reconstructing the cause meant
        diffing two manifests by hand.
        """
        workspace, a, b = two_runs

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 0, result.output
        assert "prompt changed" in tracker.runs[0].tags[CHANGED]
        assert "extract" in tracker.runs[0].tags[CHANGED]

    def test_comparing_a_run_with_itself_names_nothing_and_still_carries_the_tag(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 4): the one where nothing moved between the runs.

        Present and empty. An absent tag is indistinguishable from a comparison
        recorded before this rule existed, which is the argument R11.9 row 3
        makes for `dossier.regressed` -- and the same two tags would otherwise
        disagree about what an absence means.
        """
        workspace, a, _ = two_runs

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, a
        )

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].tags[CHANGED] == ""

    def test_the_cause_is_read_from_the_manifests_not_from_the_pipeline_on_disk(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """The claim underneath: two runs, two pinned plans, one diff.

        The prompt is edited a third time before the comparison. What is named is
        still the difference between the two runs -- `extract`, whose prompt moved
        between them -- and not a third state neither run was made in.
        """
        workspace, a, b = two_runs
        prompt = workspace / "pipelines" / PIPELINE / "prompts" / "01_extract.md"
        prompt.write_text(
            prompt.read_text(encoding="utf-8") + "\n\nA third edit.\n", encoding="utf-8"
        )

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 0, result.output
        named = tracker.runs[0].tags[CHANGED]
        assert named == "extract (prompt changed)", named
