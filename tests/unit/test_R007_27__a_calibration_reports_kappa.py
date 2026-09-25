"""R7.27 — a calibration reports Cohen's kappa between the judge and the reviewer.

Agreement counts every case the two agreed on, including the ones they would
have agreed on by chance. R7.11's sample is 12 supported and 8 unsupported, so a
judge that answers "supported" to everything agrees on 60% of it without
reading a word. Kappa takes that chance agreement out: 1 is perfect, 0 is no
better than chance.

Pure arithmetic over two sets of verdicts, proved here with no judge.
"""

from __future__ import annotations

from dossier.domain.judges import agreement, kappa


def _human(count: int = 20, supported: int = 12) -> dict[str, bool]:
    """R7.11's sample: cases 0-11 marked supported, 12-19 unsupported."""
    return {f"rc-{index:02d}": index < supported for index in range(count)}


class TestACalibrationReportsKappa:
    """R7.27 — agreement beyond chance, and when there is no chance to go beyond."""

    def test_a_judge_that_agrees_on_every_case_is_at_one(self):
        """Row 1: the one where the judge agrees on every case."""
        human = _human()

        assert kappa(verdicts=dict(human), human=human) == 1.0

    def test_a_judge_that_never_says_no_is_at_zero(self):
        """Row 2: the one where agreement flatters a judge that never says no."""
        human = _human()
        verdicts = dict.fromkeys(human, True)

        measured, _ = agreement(verdicts=verdicts, human=human)

        assert measured == 0.6
        assert kappa(verdicts=verdicts, human=human) == 0.0

    def test_one_unsupported_claim_let_through_costs_a_tenth(self):
        """Row 3: the one where one unsupported claim slips through."""
        human = _human()
        verdicts = {**human, "rc-19": True}

        measured = kappa(verdicts=verdicts, human=human)

        assert measured is not None
        assert f"{measured:.2f}" == "0.89"

    def test_a_case_the_judge_could_not_be_asked_counts_as_the_opposite_verdict(self):
        """The one where a missing verdict is scored as the wrong one, as agreement scores it.

        Dropping the case would measure kappa over 19 cases and agreement over
        20, and the two would disagree about how many disagreements there were.
        """
        human = _human()
        missing = {case: verdict for case, verdict in human.items() if case != "rc-00"}
        wrong = {**human, "rc-00": False}

        assert kappa(verdicts=missing, human=human) == kappa(verdicts=wrong, human=human)
        assert f"{kappa(verdicts=missing, human=human):.2f}" == "0.90"

    def test_a_reviewer_who_used_one_verdict_leaves_nothing_to_measure(self):
        """Row 4, counter-example: the one where the reviewer used only one verdict.

        Chance agreement then depends on the judge alone: a judge that agrees on
        every case gives 0/0, and one that does not gives exactly 0. Neither says
        anything about the judge, so neither is reported as a figure.
        """
        human = dict.fromkeys(_human(), True)
        mixed = {**human, "rc-19": False}

        assert kappa(verdicts=dict(human), human=human) is None
        assert kappa(verdicts=mixed, human=human) is None
