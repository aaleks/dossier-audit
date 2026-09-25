"""R7.28 — a calibration reports the supported and the unsupported cases apart.

Agreement pools two questions: does the judge accept a supported answer, and
does it catch an unsupported one? The second is the judge's whole job (R7.12),
and a judge strong on the first can hide a weak second inside one figure. So
each half is reported as how many the judge agreed on out of how many there
were -- counts, because 8 of 8 and 80 of 80 are both 100%.
"""

from __future__ import annotations

from dossier.domain.judges import Tally, by_verdict


def _human(count: int = 20, supported: int = 12) -> dict[str, bool]:
    """R7.11's sample: cases 0-11 marked supported, 12-19 unsupported."""
    return {f"rc-{index:02d}": index < supported for index in range(count)}


class TestSupportedAndUnsupportedCasesAreReportedApart:
    """R7.28 — each half, as agreed out of cases."""

    def test_a_judge_that_agrees_on_every_case_clears_both_halves(self):
        """Row 1: the one where both halves are clean."""
        human = _human()

        assert by_verdict(verdicts=dict(human), human=human) == (
            Tally(agreed=12, cases=12),
            Tally(agreed=8, cases=8),
        )

    def test_a_judge_that_never_says_no_catches_nothing(self):
        """Row 2: the one where the half that matters is empty."""
        human = _human()

        supported, unsupported = by_verdict(verdicts=dict.fromkeys(human, True), human=human)

        assert supported == Tally(agreed=12, cases=12)
        assert unsupported == Tally(agreed=0, cases=8)
        assert unsupported.rate == 0.0

    def test_a_case_the_judge_could_not_be_asked_counts_against_its_own_half(self):
        """Row 3: the one where a case the judge could not be asked counts against it."""
        human = _human()
        verdicts = {case: verdict for case, verdict in human.items() if case != "rc-00"}

        assert by_verdict(verdicts=verdicts, human=human) == (
            Tally(agreed=11, cases=12),
            Tally(agreed=8, cases=8),
        )

    def test_a_half_with_no_cases_has_no_rate(self):
        """Row 4, counter-example: the one where there is nothing to catch.

        No unsupported case is not the same as every unsupported case caught, so
        the half has counts and no percentage -- 0 of 0 read as 100% would be the
        judge credited for a test it never sat.
        """
        human = dict.fromkeys(_human(), True)

        supported, unsupported = by_verdict(verdicts=dict(human), human=human)

        assert supported == Tally(agreed=20, cases=20)
        assert supported.rate == 1.0
        assert unsupported == Tally(agreed=0, cases=0)
        assert unsupported.rate is None
