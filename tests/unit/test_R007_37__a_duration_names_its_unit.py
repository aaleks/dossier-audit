"""R7.37 — a `duration` is a whole number of days, weeks, months or years, and
nothing else is a duration.

Written `<number> <unit>`, singular or plural, in any case, or as ISO 8601 with
one component. A value that is not one is unreadable, reported as not a
well-formed duration rather than as a mismatch -- as a malformed date is.

The counter-examples are the rule. A bare `90` asks "ninety of what", which is
the question `07/08/2026` asks, and it is refused for the same reason: a scorer
that guessed would be confidently wrong about every field whose unit it
guessed. Values are `_fixtures.md`'s "Fields on the contracts".
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import FieldKind, GoldField, Verdict, score_field

GROUNDED = FieldCheck(FieldVerdict.VALID)
NOTICE = Evidence(document="ACME-2024", span="on ninety (90) days' written notice")


def scored(value, gold):
    return score_field(
        record=FieldRecord(field="notice_period", value=value, source=NOTICE),
        gold=GoldField(value=gold),
        check=GROUNDED,
        kind=FieldKind.DURATION,
    )


class TestADurationNamesItsUnit:
    """R7.37 — a number and one of four units, and nothing else read as a length."""

    def test_ninety_days_is_ninety_days(self):
        """Row 1 — the one where the notice period is read as written."""
        assert scored("90 days", "90 days").verdict is Verdict.CORRECT

    def test_iso_8601_reads_the_same_length(self):
        """Row 2 — the one written the ISO way."""
        assert scored("P90D", "90 days").verdict is Verdict.CORRECT

    def test_a_singular_unit_in_any_case_reads(self):
        """Row 3 — the one where `1 Year` is `1 year`."""
        assert scored("1 Year", "1 year").verdict is Verdict.CORRECT

    def test_a_bare_number_names_no_unit(self):
        """Row 4, counter-example — the one where ninety of what is not said."""
        score = scored(90, "90 days")

        assert score.verdict is Verdict.INCORRECT
        assert "not a well-formed duration" in score.detail

    def test_business_days_are_not_a_length(self):
        """Row 5, counter-example — the one whose length depends on a calendar."""
        score = scored("90 business days", "90 days")

        assert score.verdict is Verdict.INCORRECT
        assert "not a well-formed duration" in score.detail

    def test_two_units_are_not_one_duration(self):
        """Row 6, counter-example — the one where `18 months` is how to say it."""
        score = scored("P1Y6M", "18 months")

        assert score.verdict is Verdict.INCORRECT
        assert "not a well-formed duration" in score.detail
