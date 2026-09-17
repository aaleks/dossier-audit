"""R7.14 — `dossier calibrate` measures a judge against the gold set's sample. The
arithmetic, which is pure and lives in the domain.

What `calibrate_field` writes is proved beside this file; what it *measures* --
the proportion, which cases count, and the minimum below which no figure is
produced -- is decided here with two mappings and no model. This is the layer
mutation testing can afford, and the figure a threshold is set from should be
in it.
"""

from __future__ import annotations

import pytest

from dossier.domain.judges import MINIMUM_SAMPLE, NotCalibrated, agreement, require_measurable


def _human(count: int = 20, supported: int = 12) -> dict[str, bool]:
    return {str(index): index < supported for index in range(count)}


class TestAgreementIsMeasuredOverTheReviewersCases:
    """R7.14 rows 1 and 3, at the decision."""

    def test_nineteen_of_twenty_is_ninety_five_percent_and_names_the_one(self):
        """Row 1's figure: the one where the judge disagreed on case 7."""
        human = _human()
        verdicts = {**human, "7": not human["7"]}

        measured, disagreed = agreement(verdicts=verdicts, human=human)

        assert measured == 0.95
        assert disagreed == ("7",)

    def test_a_case_the_judge_could_not_answer_counts_as_a_disagreement(self):
        """The one where the judge failed on the hard half.

        Absent from the verdicts is not dropped from the sample: a judge scored
        only on the cases it managed would report a figure the corpus does not
        support.
        """
        human = _human()
        verdicts = {case: verdict for case, verdict in human.items() if case != "3"}

        measured, disagreed = agreement(verdicts=verdicts, human=human)

        assert measured == 0.95
        assert disagreed == ("3",)

    def test_a_judge_agreeing_with_everything_scores_the_supported_share(self):
        """The floor R7.11 names: twelve of twenty supported, so 0.6 for a yes-man."""
        human = _human()

        measured, _ = agreement(verdicts=dict.fromkeys(human, True), human=human)

        assert measured == 0.6

    def test_no_reviewed_cases_is_refused(self):
        """The one where there is nothing to agree with."""
        with pytest.raises(ValueError):
            agreement(verdicts={}, human={})

    def test_a_sample_below_the_minimum_is_refused_naming_the_count(self):
        """Row 3: the one nineteen cases long, refused before any judge call."""
        with pytest.raises(NotCalibrated) as error:
            require_measurable("root_cause", MINIMUM_SAMPLE - 1)

        assert "19" in str(error.value) and "root_cause" in str(error.value)

    def test_exactly_the_minimum_is_measurable(self):
        """Counter-example: the one exactly at twenty; the bound is inclusive."""
        require_measurable("root_cause", MINIMUM_SAMPLE)
