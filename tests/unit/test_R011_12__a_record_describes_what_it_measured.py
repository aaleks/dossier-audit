"""R11.12 — an eval and a comparison describe themselves from the figures printed.

MLflow's Description is the first thing on a run's page and has been empty on
every record dossier has written. It is the one field that can say, without a
click, what this run was and what it found.

Generated, never authored: every line restates something the command printed. A
figure appearing only in a description would be a second way of arriving at one,
which is what spec 011 exists to forbid -- so every test here checks the
description against the same values the report was built from.
"""

from __future__ import annotations

from dossier.domain.scoring import FieldDelta, FieldTotal
from dossier.domain.tracking import comparison_description, eval_description

RUN_ID = "20260806T142203Z-4f1a"
SECOND_RUN_ID = "20260907T090000Z-bbbb"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
PIPELINE_HASH = "2f60a7d3"
GOLD_HASH = "3b7e1d90" + "0" * 56

# The scoring example (R7.2), as `per_field` returns it.
TOTALS = (
    FieldTotal(field="loss_amount", correct=4, scored=4),
    FieldTotal(field="resolution_date", correct=3, scored=4),
    FieldTotal(field="severity", correct=4, scored=4),
    FieldTotal(field="affected_systems", correct=3, scored=4),
    FieldTotal(field="root_cause", correct=2, scored=4),
)

# The comparison example (R7.8): the overall improves while one field regresses.
DELTAS = (
    FieldDelta(
        field="affected_systems",
        before=FieldTotal(field="affected_systems", correct=3, scored=4),
        after=FieldTotal(field="affected_systems", correct=2, scored=4),
    ),
    FieldDelta(
        field="root_cause",
        before=FieldTotal(field="root_cause", correct=2, scored=4),
        after=FieldTotal(field="root_cause", correct=4, scored=4),
    ),
)


def _described(**overrides) -> str:
    fields = {
        "run_id": RUN_ID,
        "pipeline": "incident-audit",
        "model": MODEL,
        "pipeline_hash": PIPELINE_HASH,
        "gold": "incidents",
        "gold_hash": GOLD_HASH,
        "documents": 4,
        "totals": TOTALS,
        "withheld": {},
    }
    return eval_description(**{**fields, **overrides})


class TestARecordDescribesWhatItMeasured:
    """R11.12 — an eval and a comparison describe themselves."""

    def test_an_eval_describes_the_run_the_model_and_the_gold_set_it_scored(self):
        """Example 1: the one that answers "what was this?" without a click."""
        described = _described()

        assert RUN_ID in described
        assert MODEL in described
        assert PIPELINE_HASH in described
        assert "gold incidents 3b7e1d90" in described
        assert "4 documents" in described

    def test_an_eval_describes_the_overall_and_the_weakest_field(self):
        """Example 1, the figures: the two a person reads first (R7.2).

        `80.0%` and `root_cause 50.0%` are the report's own numbers, computed
        from the same totals the report was built from -- never recomputed here
        from anything else.
        """
        described = _described()

        assert "overall 80.0%" in described
        assert "5 fields" in described
        assert "weakest root_cause 50.0%" in described

    def test_a_withheld_field_is_named_with_its_reason_and_no_percentage(self):
        """Example 2: the one where a judge may not be quoted (R7.15).

        The terminal prints the reason instead of a figure, and so does this. A
        description that silently dropped the field would read as a gold set that
        never verified it, which is a different problem wanting different work.
        """
        described = _described(
            withheld={"root_cause": "calibration stale"},
            totals=tuple(total for total in TOTALS if total.field != "root_cause"),
        )

        assert "withheld root_cause — calibration stale" in described
        assert "50.0%" not in described
        assert "overall 87.5%" in described, "the overall covers the fields it reported"

    def test_a_comparison_describes_both_runs_and_what_moved(self):
        """Example 3: the one the change gate exists to produce."""
        described = comparison_description(
            runs=(RUN_ID, SECOND_RUN_ID),
            pipeline="incident-audit",
            models=(MODEL, MODEL),
            gold="incidents",
            gold_hash=GOLD_HASH,
            documents=4,
            rows=DELTAS,
            overalls=(
                FieldTotal(field="overall", correct=16, scored=20),
                FieldTotal(field="overall", correct=18, scored=20),
            ),
        )

        assert f"compare {RUN_ID} -> {SECOND_RUN_ID}" in described
        assert "overall 80.0% -> 90.0% (+10.0)" in described
        assert "regressed affected_systems" in described
        assert MODEL in described

    def test_a_comparison_that_regressed_nothing_says_so(self):
        """Counter-example: the one where the change gate has nothing to flag.

        Said rather than omitted. A description with no regression line reads as
        one written before the line existed, which is the ambiguity R11.9 row 3
        refuses for the tag.
        """
        improved = (
            FieldDelta(
                field="root_cause",
                before=FieldTotal(field="root_cause", correct=2, scored=4),
                after=FieldTotal(field="root_cause", correct=4, scored=4),
            ),
        )

        described = comparison_description(
            runs=(RUN_ID, SECOND_RUN_ID),
            pipeline="incident-audit",
            models=(MODEL, MODEL),
            gold="incidents",
            gold_hash=GOLD_HASH,
            documents=4,
            rows=improved,
            overalls=(
                FieldTotal(field="overall", correct=16, scored=20),
                FieldTotal(field="overall", correct=18, scored=20),
            ),
        )

        assert "regressed nothing" in described

    def test_an_eval_that_scored_nothing_describes_no_overall(self):
        """The boundary: a gold set that verified none of the run's documents.

        There is no overall to state, so none is stated. Printing `overall 0.0%`
        would read as a run that got everything wrong (R7.3 row 4).
        """
        described = _described(totals=())

        assert "overall" not in described
        assert RUN_ID in described, "it still says what it was"
