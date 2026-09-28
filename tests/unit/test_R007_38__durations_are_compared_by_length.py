"""R7.38 — two durations are the same answer when they are the same length, and
a month is never a number of days.

A week is seven days and a year is twelve months, exactly, so those convert.
A month is 28 to 31 days and a year 365 or 366, so nothing converts between
days or weeks and months or years. Three months' notice and ninety days'
notice are different notice, and a scorer that called them equal would be
right by convention and wrong about the contract.

The counter-examples say why in the detail, because "does not match" alone
would send a reviewer to check a number that was never the problem.
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import FieldKind, GoldField, Verdict, score_field

GROUNDED = FieldCheck(FieldVerdict.VALID)
NOTICE = Evidence(document="GLOBEX-2023", span="three (3) months' written notice")


def scored(value, gold):
    return score_field(
        record=FieldRecord(field="notice_period", value=value, source=NOTICE),
        gold=GoldField(value=gold),
        check=GROUNDED,
        kind=FieldKind.DURATION,
    )


class TestDurationsAreComparedByLength:
    """R7.38 — the same length, converted only where the conversion is exact."""

    def test_twelve_weeks_are_eighty_four_days(self):
        """Row 1 — the one where a week is exactly seven days."""
        assert scored("12 weeks", "84 days").verdict is Verdict.CORRECT

    def test_twenty_four_months_are_two_years(self):
        """Row 2 — the one where a year is exactly twelve months."""
        assert scored("24 months", "2 years").verdict is Verdict.CORRECT

    def test_thirteen_weeks_are_not_ninety_days(self):
        """Row 3 — the one where the conversion is exact and the lengths differ."""
        score = scored("13 weeks", "90 days")

        assert score.verdict is Verdict.INCORRECT
        assert "does not match" in score.detail

    def test_ninety_days_are_not_three_months(self):
        """Row 4, counter-example — the one where a month is not a number of days."""
        score = scored("90 days", "3 months")

        assert score.verdict is Verdict.INCORRECT
        assert "a month is not a fixed number of days" in score.detail

    def test_a_year_is_not_three_hundred_and_sixty_five_days(self):
        """Row 5, counter-example — the one where a year is not either."""
        score = scored("1 year", "365 days")

        assert score.verdict is Verdict.INCORRECT
        assert "a year is not a fixed number of days" in score.detail
