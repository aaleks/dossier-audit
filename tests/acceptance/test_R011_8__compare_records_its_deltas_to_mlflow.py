"""R11.8 — a `dossier eval --compare a b` is one MLflow run of per-field deltas.

The outer loop for the change gate's record. What a person observes is the figures
the comparison table prints, in an experiment they can open a month later — because
the delta is the one number neither compared run holds, and until now it existed
only in a terminal.

Both runs are of `incident-audit` over the four documents of the scoring example,
the second after the prompt changed: run `a` agrees with gold except on the four
disagreements of the scoring example, run `b` except on two of them. Those are
`_fixtures.md`'s comparison example, so every figure asserted here is one a person
wrote down rather than one this test invented.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeTracker
from tests.scoring_example import PIPELINE, RoutedModel

EXPERIMENT = "dossier-audit/incident-audit/compare"

# The comparison example of `_fixtures.md`, as metric names. `a/` and `b/` are the
# two columns the table prints and `delta/` is the third, so the terminal and
# MLflow cannot disagree about any of the three (spec 011).
EXPECTED = {
    "a/loss_amount": 100.0,
    "b/loss_amount": 100.0,
    "delta/loss_amount": 0.0,
    "a/resolution_date": 75.0,
    "b/resolution_date": 100.0,
    "delta/resolution_date": 25.0,
    "a/severity": 100.0,
    "b/severity": 100.0,
    "delta/severity": 0.0,
    "a/affected_systems": 75.0,
    "b/affected_systems": 50.0,
    "delta/affected_systems": -25.0,
    "a/root_cause": 50.0,
    "b/root_cause": 100.0,
    "delta/root_cause": 50.0,
    "a/overall": 80.0,
    "b/overall": 90.0,
    "delta/overall": 10.0,
}


@pytest.fixture
def tracker(two_runs: tuple[Path, str, str], monkeypatch) -> FakeTracker:
    """Tracking switched on after both runs, recording to a fake that counts."""
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


class TestCompareRecordsItsDeltasToMLflow:
    """R11.8 — a comparison is one MLflow run of per-field deltas, with no traces."""

    def test_a_comparison_records_both_scores_and_the_delta_for_every_field(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where two configurations are read side by side.

        Every figure the table prints: each field in `a`, in `b`, and the delta,
        and the same three for the overall. The delta is the reason this rule
        exists — neither compared run holds it.
        """
        workspace, a, b = two_runs

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1, "one comparison is one MLflow run"
        assert tracker.runs[0].metrics == EXPECTED

    def test_the_comparison_lands_in_its_own_experiment_naming_both_runs(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one read back to ask which two runs these deltas are between.

        Its own experiment kind, because a delta is not an accuracy and the two
        would read as the same sort of number side by side. Both run ids as
        params, the gold set by its full hash (R0.7), and no traces — a
        comparison reproduces from cache and asks no model (R7.10).
        """
        workspace, a, b = two_runs

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 0, result.output
        run = tracker.runs[0]
        assert run.experiment == EXPERIMENT
        assert run.tags["dossier.kind"] == "compare"
        assert run.params["a"] == a
        assert run.params["b"] == b
        # Each run's own pin, from its own manifest. One `model` param would be a
        # claim about both runs that is false in exactly the case the change gate
        # exists for -- comparing two models (R7.8).
        assert run.params["a/model"] == RoutedModel.model_id
        assert run.params["b/model"] == RoutedModel.model_id
        assert len(run.tags["dossier.gold_hash"]) == 64
        assert tracker.traces == [], "no (step, document) work to trace"

    def test_a_field_that_did_not_move_records_a_delta_of_zero(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 3: the one where `severity` was right in both runs.

        Recorded as zero rather than omitted. A field left out because it did not
        move is indistinguishable from one nobody scored (R7.8 row 4).
        """
        workspace, a, b = two_runs

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].metrics["delta/severity"] == 0.0

    def test_a_comparison_over_different_documents_records_nothing(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 4): the one where there was nothing to compare.

        A comparison over different documents is refused (R7.8 row 3), and a
        refusal records nothing: there is no delta, so there is no figure. As a
        calibration that measured nothing records nothing (R11.5 row 4).
        """
        workspace, a, b = two_runs
        manifest = workspace / "runs" / b / "manifest.json"
        held = json.loads(manifest.read_text(encoding="utf-8"))
        held["plan"]["documents"] = held["plan"]["documents"][:3]
        manifest.write_text(json.dumps(held, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 2, result.output
        assert tracker.runs == [], "nothing was compared, so nothing is recorded"
