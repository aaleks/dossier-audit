"""R11.3 — a `dossier eval` is one MLflow run with one metric per scored field.

The figures are the ones R7.2 prints, recorded as the same percentages -- `75.0`,
not `0.75` -- so the terminal and MLflow cannot disagree. The gold set is named,
and tagged with a hash of its contents: two evals over gold sets that differ by
one answer are not comparable, and the hash is what says so.

Rows 3 and 4 -- a judge's calibrated agreement recorded as a param, and a judge
below its threshold recording no metric at all -- waited for R7.11, which now
produces a calibration. All five rows are transcribed, and all five run in the
default suite: the slice closed, so the `outer_loop` markers came off.

The recording decision is `record_eval`, handed a `FakeTracker`. The totals are
`_fixtures.md`'s scoring example: 4/4, 3/4, 4/4, 3/4 and 2/4.
"""

from __future__ import annotations

import re

from tests.fakes import FakeTracker

from dossier.application.eval import record_eval
from dossier.domain.judges import Calibration
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

# R7.5's numbers, which R11.3 rows 3 and 4 quote: eligible at 0.91, not at 0.78,
# against a configured 0.85. The judge is the one R7.11 calibrated, named by a
# pinned identifier (R9.14) because the figure is meaningless without it.
JUDGE_MODEL = "openai:gpt-5.4-mini"
RUBRIC_HASH = "0e52dd18" * 8
# Twenty is R7.11's minimum. Below it `is_eligible` raises rather than returning
# False -- a judge nobody measured is not a judge that scored badly -- and that
# is a different rule with its own test.
CALIBRATED = Calibration(
    judge_model=JUDGE_MODEL, rubric_hash=RUBRIC_HASH, agreement=0.91, sample_size=20
)
UNDER_THRESHOLD = CALIBRATED.model_copy(update={"agreement": 0.78})


def _record(
    tracker: FakeTracker, *, totals=SCORING_EXAMPLE, gold_files=GOLD_FILES, **judge_arguments
) -> None:
    """One eval recorded. Judge arguments are forwarded only when a test gives them.

    Rows 1, 2 and 5 are about what an eval records whether or not a judge was
    involved, so they say nothing about one. `record_eval` defaults both
    arguments, and a test that passed them anyway would be asserting the default
    rather than the row it exists for.
    """
    record_eval(
        tracker,
        experiment=EXPERIMENT,
        pipeline="incident-audit",
        run_id=RUN_ID,
        model=MODEL,
        gold="gold/incidents",
        gold_files=gold_files,
        totals=totals,
        **judge_arguments,
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

    def test_a_calibrated_judge_records_its_agreement_and_which_judge_gave_it(self):
        """Example 3: the one whose judge agreed with the reviewer often enough.

        The figure is recorded with the model that produced it. An agreement
        number on its own says a judge agreed with a human without saying which
        judge or on what question, and two evals under different judges would
        then be read as the same measurement (R7.11 row 2).
        """
        tracker = FakeTracker()

        _record(tracker, judges={"root_cause": CALIBRATED}, thresholds={"root_cause": 0.85})

        params = tracker.runs[0].params
        # The value, not its formatting: a param is a string, and asserting
        # "0.91" would break on a client that writes "0.910".
        assert float(params["judge/root_cause/agreement"]) == 0.91
        assert params["judge/root_cause/model"] == JUDGE_MODEL

    def test_a_judge_below_its_threshold_reports_no_accuracy_for_that_field(self):
        """Example 4: the one where the judge was measured and did not do well enough.

        R7.5's gate, seen in the record. The field is not reported, and the run
        says why -- a metric that is simply missing reads as a field nobody
        verified (row 5), which is a different thing and wants different work.
        The fields no judge scored are unaffected.
        """
        tracker = FakeTracker()

        _record(
            tracker, judges={"root_cause": UNDER_THRESHOLD}, thresholds={"root_cause": 0.85}
        )

        run = tracker.runs[0]
        assert "accuracy/root_cause" not in run.metrics
        assert "accuracy/severity" in run.metrics
        why = run.tags["dossier.judge.root_cause"]
        assert "0.78" in why and "0.85" in why
