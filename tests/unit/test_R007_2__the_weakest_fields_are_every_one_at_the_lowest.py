"""R7.2 — results are reported per field, and the weakest field is marked. The decision.

The acceptance test beside this one proves `dossier eval` marks `root_cause` at
50.0% (row 3). Which fields are the weakest is `weakest`'s to decide, from the
counts: two fields at the lowest are both marked, 1 of 3 and 2 of 6 are the same
score however floating point rounds them, and when every field scores the same
none is marked.
"""

from __future__ import annotations

import pytest

from dossier.domain.scoring import FieldTotal, weakest


def _totals(*scores: tuple[str, int, int]) -> list[FieldTotal]:
    return [
        FieldTotal(field, correct=correct, scored=scored) for field, correct, scored in scores
    ]


class TestTheWeakestFieldsAreEveryOneAtTheLowest:
    """R7.2 rows 3, 5, 6 and 7 — the lowest by the counts, every field at it, or none."""

    @pytest.mark.parametrize(
        ("scores", "marked"),
        [
            # Row 3: the scoring example's five fields.
            (
                [
                    ("loss_amount", 4, 4),
                    ("resolution_date", 3, 4),
                    ("severity", 4, 4),
                    ("affected_systems", 3, 4),
                    ("root_cause", 2, 4),
                ],
                ("root_cause",),
            ),
            # Row 3, the lowest listed first and listed second: its place in the
            # report decides nothing.
            (
                [("root_cause", 1, 4), ("loss_amount", 4, 4), ("severity", 3, 4)],
                ("root_cause",),
            ),
            (
                [("loss_amount", 4, 4), ("root_cause", 2, 4), ("severity", 3, 4)],
                ("root_cause",),
            ),
            # Row 5: two fields tied at the lowest.
            (
                [
                    ("loss_amount", 4, 4),
                    ("resolution_date", 3, 4),
                    ("affected_systems", 3, 4),
                    ("root_cause", 4, 4),
                ],
                ("resolution_date", "affected_systems"),
            ),
            # Row 6: 1 of 3 and 2 of 6, the same score by their counts.
            (
                [("root_cause", 1, 3), ("loss_amount", 2, 6), ("severity", 5, 6)],
                ("root_cause", "loss_amount"),
            ),
            # Row 6's other side: 5 of 6 against 4 of 5 is 25 against 24.
            ([("severity", 5, 6), ("resolution_date", 4, 5)], ("resolution_date",)),
        ],
    )
    def test_every_field_at_the_lowest_is_marked(self, scores, marked):
        assert weakest(_totals(*scores)) == marked

    def test_every_field_at_one_score_marks_none(self):
        """Row 7, counter-example: the one where 3 of 4, 3 of 4 and 6 of 8 are all 75.0%."""
        totals = _totals(
            ("resolution_date", 3, 4), ("affected_systems", 3, 4), ("severity", 6, 8)
        )

        assert weakest(totals) == ()
