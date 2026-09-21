"""R011.8 — a comparison is one MLflow run of per-field deltas, with no traces.

The application half: what `record_comparison` puts on the run. The acceptance test
beside this one proves the command makes one; this pins the shape, and in particular
the three metrics per field — both sides and the delta — because a delta alone
would force a reader back to the two runs to learn what moved from what.

The figures are the comparison example of `_fixtures.md`: `affected_systems` falling
75.0% to 50.0% while the overall rises 80.0% to 90.0%.
"""

from __future__ import annotations

from tests.fakes import FakeTracker

from dossier.application.eval import record_comparison
from dossier.domain.scoring import FieldTotal, compare_totals, overall

RUNS = ("20260806T142203Z-4f1a", "20260907T090000Z-bbbb")
MODEL = "gemini:gemini-3.5-flash-lite"
EXPERIMENT = "dossier-audit/incident-audit/compare"
GOLD_FILES = {
    "INC-4821.json": b'{"document": "INC-4821", "verified_by": "a.aleks", '
    b'"verified_at": "2026-08-14", "fields": {"severity": {"value": "major"}}}',
}


def _totals(**fields: tuple[int, int]) -> list[FieldTotal]:
    return [
        FieldTotal(field=name, correct=correct, scored=scored)
        for name, (correct, scored) in fields.items()
    ]


BEFORE = _totals(loss_amount=(4, 4), affected_systems=(3, 4), root_cause=(2, 4))
AFTER = _totals(loss_amount=(4, 4), affected_systems=(2, 4), root_cause=(4, 4))


def _record(tracker: FakeTracker, before=BEFORE, after=AFTER, **kwargs) -> None:
    record_comparison(
        tracker,
        experiment=EXPERIMENT,
        pipeline="incident-audit",
        runs=RUNS,
        models=(MODEL, MODEL),
        gold="gold/incidents",
        gold_files=GOLD_FILES,
        rows=compare_totals(before, after),
        overalls=(overall(before), overall(after)),
        **kwargs,
    )


class TestAComparisonRecordsOneRunOfDeltas:
    """R11.8 — one run, three metrics per field, and no traces."""

    def test_every_field_records_both_sides_and_the_delta(self):
        """Example 1: the one where two configurations are read side by side.

        `a/`, `b/` and `delta/` for each field. The delta is the figure neither
        compared run holds, and the two sides are what make it readable without
        opening them.
        """
        tracker = FakeTracker()

        _record(tracker)

        assert len(tracker.runs) == 1
        metrics = tracker.runs[0].metrics
        assert metrics["a/affected_systems"] == 75.0
        assert metrics["b/affected_systems"] == 50.0
        assert metrics["delta/affected_systems"] == -25.0

    def test_the_overall_is_recorded_as_a_field_is(self):
        """The one where the headline moved the other way.

        The overall rises while `affected_systems` falls — recorded on the same
        run, so the figure that hides a regression and the regression itself are
        read together (R7.8 row 2).
        """
        tracker = FakeTracker()

        _record(tracker)

        metrics = tracker.runs[0].metrics
        assert metrics["a/overall"] == 75.0
        # The figure, not the rendering. The report prints `83.3%` with a format
        # string; recording a rounded number instead would make MLflow a second
        # way of arriving at the value rather than a second place to read it.
        assert round(metrics["b/overall"], 1) == 83.3
        assert round(metrics["delta/overall"], 1) == 8.3

    def test_the_run_names_both_runs_their_models_and_the_gold_set(self):
        """Example 2: the one read back to ask which two runs these deltas are between.

        Each run's own pinned model, from its own manifest: one `model` param
        would be a claim about both that is false in exactly the case the change
        gate exists for.
        """
        tracker = FakeTracker()

        _record(tracker)

        run = tracker.runs[0]
        assert run.experiment == EXPERIMENT
        assert run.tags["dossier.kind"] == "compare"
        assert run.params["a"] == RUNS[0]
        assert run.params["b"] == RUNS[1]
        assert run.params["a/model"] == MODEL
        assert run.params["b/model"] == MODEL
        assert run.params["gold"] == "incidents"
        assert len(run.tags["dossier.gold_hash"]) == 64

    def test_a_comparison_records_no_traces(self):
        """The one where there is no unit of work to trace.

        A comparison reproduces both runs from their manifests and caches and asks
        no model (R7.10), so there is no (step, document) pair to trace. The two
        runs it reads carry their own, recorded when they ran.
        """
        tracker = FakeTracker()

        _record(tracker)

        assert tracker.traces == []
        assert tracker.spans == []
        assert tracker.runs[0].status == "OK", "opened and closed here"

    def test_a_field_only_one_run_scored_records_its_side_and_no_delta(self):
        """*counter-example* — the one where there is nothing to subtract.

        `severity` exists in `b` alone, so `b/severity` is recorded and
        `delta/severity` is not. A delta of zero here would claim the field held
        steady, which nobody measured.
        """
        tracker = FakeTracker()

        _record(tracker, after=_totals(loss_amount=(4, 4), severity=(4, 4)))

        metrics = tracker.runs[0].metrics
        assert metrics["b/severity"] == 100.0
        assert "delta/severity" not in metrics
        assert "a/severity" not in metrics
