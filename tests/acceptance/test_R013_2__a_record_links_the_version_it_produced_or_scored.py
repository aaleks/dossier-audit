"""R13.2 - a record links the version it produced, or the version it scored.

A run **made** a version; an eval **measured** one. MLflow holds those as
different edges, and a live spike confirmed they are not interchangeable:
`log_outputs` fills a run's own model column, which is the column this spec
exists for, while the registry's `source_run_id` fills the model's source field
and leaves the run's column empty.

One edge in both directions would make an eval look like it produced the
pipeline it scored, which is the only claim on either page that a reader would
act on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeTracker, FakeVersionRegistry
from tests.scoring_example import PIPELINE


@pytest.fixture
def recorded(two_runs: tuple[Path, str, str], monkeypatch):
    """Tracking on after both runs, at a fake tracker and a fake registry."""
    import dossier.cli.main as cli

    tracker = FakeTracker()
    versions = FakeVersionRegistry()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(cli, "build_version_registry", lambda settings: versions, raising=False)
    return tracker, versions


class TestARecordLinksTheVersionItProducedOrScored:
    """R13.2 - an output edge for a run, an input edge for an eval."""

    def test_a_run_links_the_version_on_its_outputs(
        self, two_runs: tuple[Path, str, str], monkeypatch, recorded
    ):
        """Example 1: the one that fills the column this spec is about.

        `produced`, not `scored`. A run built this version; the run page's
        Logged models column is what a person opens to see what it built.
        """
        tracker, versions = recorded
        workspace, _, _ = two_runs

        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0

        assert len(versions.versions) == 1
        run = tracker.runs[-1]
        assert run.produced == [versions.versions[0].version_id]
        assert run.scored == [], "a run measures nothing"

    def test_an_eval_links_the_version_on_its_inputs(
        self, two_runs: tuple[Path, str, str], monkeypatch, recorded
    ):
        """Example 2: the one where the direction is the whole claim.

        An eval consumes a version. Recording it as an output would put the
        eval on the pipeline's provenance, which is a claim nobody could act on
        correctly.
        """
        tracker, versions = recorded
        workspace, a, _ = two_runs

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert run.scored, "the eval recorded no version at all"
        assert run.scored == [versions.versions[0].version_id]
        assert run.produced == [], "an eval produces no pipeline version"

    def test_an_eval_of_an_untracked_run_still_records_what_it_scored(
        self, two_runs: tuple[Path, str, str], monkeypatch, recorded
    ):
        """Example 3: the one where nothing registered the version first.

        `two_runs` ran with tracking off, so the eval below is the first thing
        to see this version at all. It registers it and links it as an input:
        what was scored is recorded, and nothing claims to have produced it.
        """
        tracker, versions = recorded
        workspace, _, _ = two_runs

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert len(versions.versions) == 1, "the eval registered it"
        assert tracker.runs[-1].scored == [versions.versions[0].version_id]
        assert all(run.produced == [] for run in tracker.runs)

    def test_a_comparison_links_both_versions_it_measured(
        self, two_runs: tuple[Path, str, str], monkeypatch, recorded
    ):
        """Example 4: the one where naming one would be half a claim.

        A comparison measures two versions. `a/model` and `b/model` are already
        two params for the same reason (R11.11 row 3): one value would be false
        in exactly the case the change gate exists for.
        """
        tracker, versions = recorded
        workspace, a, b = two_runs

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert len(versions.versions) == 2, "the two runs are two versions"
        assert set(run.scored) == {version.version_id for version in versions.versions}
        assert run.produced == []

    def test_tracking_off_links_nothing(self, two_runs: tuple[Path, str, str], monkeypatch):
        """Counter-example, row 5: the one where there is no record to link on."""
        workspace, _, _ = two_runs

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "recorded to MLflow" not in result.output
