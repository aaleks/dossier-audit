"""R11.3 — a `dossier eval` is one MLflow run with one metric per scored field.

The figures are the ones R7.2 prints, recorded as the same percentages -- `75.0`,
not `0.75` -- so the terminal and MLflow cannot disagree. The gold set is named,
and tagged with a hash of its contents: two evals over gold sets that differ by
one answer are not comparable, and the hash is what says so.

Rows 3 and 4 -- a judge's calibrated agreement, and a judge below threshold
recording no metric -- wait for R7.11: nothing produces a judge calibration yet.
They are not transcribed here, and R11.3 stays NOT MET until they are.

The recording decision is `record_eval`, handed a `FakeTracker`. The totals are
`_fixtures.md`'s scoring example: 4/4, 3/4, 4/4, 3/4 and 2/4.
"""

from __future__ import annotations

import re

from tests.fakes import FakeTracker

from dossier.application.eval import record_eval
from dossier.domain.scoring import FieldTotal

MODEL = "anthropic:claude-sonnet-4-5-20250929"
RUN_ID = "20260806T142203Z-4f1a"
EXPERIMENT = "dossier-audit/incident-audit/eval"
GOLD_FILES = {
    "INC-4821.json": b'{"document": "INC-4821"}',
    "INC-4822.json": b'{"document": "INC-4822"}',
}
SCORING_EXAMPLE = (
    FieldTotal("loss_amount", correct=4, scored=4),
    FieldTotal("resolution_date", correct=3, scored=4),
    FieldTotal("severity", correct=4, scored=4),
    FieldTotal("affected_systems", correct=3, scored=4),
    FieldTotal("root_cause", correct=2, scored=4),
)


def _record(tracker: FakeTracker, *, totals=SCORING_EXAMPLE, gold_files=GOLD_FILES) -> None:
    record_eval(
        tracker,
        experiment=EXPERIMENT,
        pipeline="incident-audit",
        run_id=RUN_ID,
        model=MODEL,
        gold="gold/incidents",
        gold_files=gold_files,
        totals=totals,
    )


class TestAnEvalRecordsOneMetricPerField:
    """R11.3 — one MLflow run, one metric per scored field (rows 1, 2 and 5)."""

    def test_an_eval_is_one_run_with_the_accuracy_it_prints_per_field(self):
        """Example 1: the one over the scoring example."""
        tracker = FakeTracker()

        _record(tracker)

        assert len(tracker.runs) == 1
        assert tracker.runs[0].metrics == {
            "accuracy/loss_amount": 100.0,
            "accuracy/resolution_date": 75.0,
            "accuracy/severity": 100.0,
            "accuracy/affected_systems": 75.0,
            "accuracy/root_cause": 50.0,
            "accuracy/overall": 80.0,
        }

    def test_the_eval_names_its_model_its_gold_set_and_the_run_it_scored(self):
        """Example 2: the one read back for what was scored, against what.

        The gold set is named `incidents` and tagged with a full 64-character
        hash of its contents (R0.7), which moves when any answer in it moves.
        """
        tracker, changed = FakeTracker(), FakeTracker()

        _record(tracker)
        _record(changed, gold_files={**GOLD_FILES, "INC-4822.json": b'{"document": "x"}'})

        run = tracker.runs[0]
        assert run.params == {"model": MODEL, "gold": "incidents"}
        assert run.tags["dossier.run_id"] == RUN_ID
        assert run.tags["dossier.kind"] == "eval"
        assert re.fullmatch(r"[0-9a-f]{64}", run.tags["dossier.gold_hash"])
        assert changed.runs[0].tags["dossier.gold_hash"] != run.tags["dossier.gold_hash"]

    def test_a_gold_set_covering_one_field_records_one_field_metric(self):
        """Counter-example (row 5): the one whose gold covers `severity` alone.

        One field metric. No zero is recorded for fields nobody verified: a
        field absent from gold is not scored at all (R7.3 row 4), and a 0.0
        would read as a field that was always wrong.
        """
        tracker = FakeTracker()

        _record(tracker, totals=(FieldTotal("severity", correct=4, scored=4),))

        fields = {name for name in tracker.runs[0].metrics if name != "accuracy/overall"}
        assert fields == {"accuracy/severity"}
