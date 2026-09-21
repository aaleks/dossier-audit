"""R011.9 — the fields a comparison regressed are named on its run.

The one thing a person opens a comparison to find. R7.8 flags a regression in the
terminal; this puts the same flag where it can be filtered on months later, which
is the difference between "which change broke `affected_systems`" being a query and
being an archaeology exercise.

A pure decision over two runs' per-field totals, so it is a `domain/` function and
needs no workspace: the counts are the comparison example of `_fixtures.md`.
"""

from __future__ import annotations

from dossier.domain.scoring import FieldTotal, compare_totals, regressed_fields


def _totals(**fields: tuple[int, int]) -> list[FieldTotal]:
    """One `FieldTotal` per field, from a (correct, scored) pair."""
    return [
        FieldTotal(field=name, correct=correct, scored=scored)
        for name, (correct, scored) in fields.items()
    ]


class TestAComparisonNamesTheFieldsThatRegressed:
    """R11.9 — the fields a comparison regressed are named on its run."""

    def test_a_regression_is_named_even_though_the_overall_improved(self):
        """Example 1: the one where the headline improved and a field got worse.

        `affected_systems` moves 75.0% to 50.0% while the overall moves 80.0% to
        90.0% — the case the change gate exists for, and the one an overall
        figure hides (R7.8 row 2).
        """
        before = _totals(
            loss_amount=(4, 4),
            resolution_date=(3, 4),
            affected_systems=(3, 4),
            root_cause=(2, 4),
        )
        after = _totals(
            loss_amount=(4, 4),
            resolution_date=(4, 4),
            affected_systems=(2, 4),
            root_cause=(4, 4),
        )

        assert regressed_fields(compare_totals(before, after)) == ("affected_systems",)

    def test_two_regressions_are_named_in_the_order_the_report_lists_them(self):
        """Example 2: the one where more than one field got worse.

        In report order, so the tag reads as the report reads. Sorting it would
        put a second ordering on the same list for no reason.
        """
        before = _totals(loss_amount=(4, 4), resolution_date=(4, 4), severity=(4, 4))
        after = _totals(loss_amount=(2, 4), resolution_date=(4, 4), severity=(1, 4))

        assert regressed_fields(compare_totals(before, after)) == ("loss_amount", "severity")

    def test_nothing_regressed_is_an_empty_answer_rather_than_no_answer(self):
        """Counter-example (row 3): the one where every field held or improved.

        An empty tuple is a real answer — we looked, and nothing regressed. The
        caller records it as a present, empty tag, because an absent one is
        indistinguishable from a comparison recorded before this rule existed
        (R11.6 row 2).
        """
        before = _totals(loss_amount=(3, 4), severity=(4, 4))
        after = _totals(loss_amount=(4, 4), severity=(4, 4))

        assert regressed_fields(compare_totals(before, after)) == ()

    def test_a_field_only_one_run_scored_has_not_regressed(self):
        """The one where the two runs do not both cover a field.

        A field with nothing to compare against did not get worse — it is
        unmeasured, and calling that a regression would report a gold set's
        coverage as a change in quality (R7.3 row 4).
        """
        before = _totals(loss_amount=(4, 4))
        after = _totals(loss_amount=(4, 4), severity=(0, 4))

        assert regressed_fields(compare_totals(before, after)) == ()

    def test_a_field_that_did_not_move_is_not_a_regression_however_it_rounds(self):
        """The boundary: the one where the same score is written two ways.

        2/3 and 4/6 are the same score, and floating point does not always agree.
        The comparison cross-multiplies the counts, so this is not a regression —
        and a flaky regression tag would be worse than none.
        """
        before = _totals(root_cause=(2, 3))
        after = _totals(root_cause=(4, 6))

        assert regressed_fields(compare_totals(before, after)) == ()
