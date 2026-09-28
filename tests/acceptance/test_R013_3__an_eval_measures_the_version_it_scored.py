"""R13.3 - an eval's accuracy is recorded against the version it scored.

The same figures R11.3 already puts on the eval's own run, sent to a second
place. That is the whole point: a metric on a run compares with other runs, and
a metric on a version compares with other versions, which is the comparison a
change gate is opened to make.

Recorded, never computed. `finish_eval` builds one `metrics` dict and hands it
to both, so the run and the version cannot disagree -- and a field the report
withheld is absent from that dict, so it is absent from both.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeTracker, FakeVersionRegistry
from tests.scoring_example import PIPELINE

FIELD = "root_cause"


@pytest.fixture
def recorded(two_runs: tuple[Path, str, str], monkeypatch):
    """Tracking on after both runs, at a fake tracker and a fake registry."""
    import dossier.cli.bootstrap as cli

    tracker = FakeTracker()
    versions = FakeVersionRegistry()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(cli, "build_version_registry", lambda settings: versions, raising=False)
    return tracker, versions


class TestAnEvalMeasuresTheVersionItScored:
    """R13.3 - the accuracy is on the version, and it is the same accuracy."""

    def test_the_accuracy_is_on_the_version_and_equals_the_run_s(
        self, two_runs: tuple[Path, str, str], monkeypatch, recorded
    ):
        """Example 1: the one that makes the Models tab worth opening.

        Asserted as equality between the two, not against a literal. A literal
        would pass if both were wrong together; this fails the moment they part
        company, which is the disagreement spec 011 forbids.
        """
        tracker, versions = recorded
        workspace, _, _ = two_runs

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        version_id = versions.versions[0].version_id
        assert run.version_metrics[version_id] == run.metrics
        assert "accuracy/overall" in run.version_metrics[version_id]

    def test_scoring_the_same_run_twice_measures_the_one_version_twice(
        self, two_runs: tuple[Path, str, str], monkeypatch, recorded
    ):
        """Example 2: the one where a version accumulates its measurements.

        Two evals, one version. A live spike confirmed MLflow keeps both values
        against the model with each carrying the run it came from, rather than
        the later silently replacing the earlier.
        """
        tracker, versions = recorded
        workspace, _, _ = two_runs

        assert _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD).exit_code == 0
        assert _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD).exit_code == 0

        assert len(versions.versions) == 1, "one version"
        version_id = versions.versions[0].version_id
        measured = [run for run in tracker.runs if version_id in run.version_metrics]
        assert len(measured) == 2, "measured by two evals"

    def test_a_withheld_field_has_no_accuracy_on_the_version_either(
        self, two_runs: tuple[Path, str, str], monkeypatch, recorded
    ):
        """Example 3: the one where a number nobody may print reaches nowhere.

        The calibration is deleted, so `root_cause` is withheld as missing
        (R7.15). `finish_eval` builds one dict for both, so a version can never
        carry an accuracy the report refused (R7.17).
        """
        tracker, versions = recorded
        workspace, _, _ = two_runs
        (workspace / "gold" / "incidents" / "calibrations" / f"{FIELD}.json").unlink()

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        version_id = versions.versions[0].version_id
        assert f"accuracy/{FIELD}" not in run.version_metrics[version_id]
        assert f"accuracy/{FIELD}" not in run.metrics
        assert run.version_metrics[version_id] == run.metrics

    def test_a_comparison_measures_no_version(
        self, two_runs: tuple[Path, str, str], monkeypatch, recorded
    ):
        """Counter-example, row 5: the one where the figure belongs to a pair.

        A comparison links both versions (R13.2 row 4) and measures neither. A
        delta is a figure about two versions and belongs to neither half of
        them, which is why it is not an accuracy in the first place (R11.8).
        """
        tracker, versions = recorded
        workspace, a, b = two_runs

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert run.scored, "both versions are linked"
        assert run.version_metrics == {}, "and neither is measured"
