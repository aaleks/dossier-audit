"""R7.26 — a calibration reports the 95% Wilson lower bound on its agreement.

Agreement says how often the judge and the reviewer agreed on this sample. The
bound says how low the judge's true rate could be and still produce that
sample, which is the figure a bar can honestly be compared with: 20 of 20 is
100%, and 20 cases cannot show better than about 84%.

Pure arithmetic over two counts, so it is proved here, in the domain, with no
judge and no sample file.
"""

from __future__ import annotations

import pytest

from dossier.domain.judges import Calibration, lower_bound, withholding

# The 95% Wilson lower bounds for R7.26's rows, to 1e-9. Each is what the
# formula gives with z the 0.975 quantile of the standard normal; z typed as
# 1.96 instead moves the first of them in its sixth decimal.
TWENTY_OF_TWENTY = 0.838874842
NINETEEN_OF_TWENTY = 0.763868807
THIRTY_EIGHT_OF_FORTY = 0.834961226


class TestACalibrationReportsTheLowerBoundOnItsAgreement:
    """R7.26 — the bound, over the same cases the agreement is over."""

    def test_twenty_of_twenty_is_bounded_near_eighty_four_percent(self):
        """Row 1: the one where a perfect score on 20 cases still only proves about 84%."""
        bound = lower_bound(agreed=20, cases=20)

        assert bound == pytest.approx(TWENTY_OF_TWENTY, abs=1e-9)
        assert f"{bound:.1%}" == "83.9%"

    def test_one_miss_costs_more_of_the_bound_than_of_the_agreement(self):
        """Row 2: the one where one miss costs more than it looks."""
        bound = lower_bound(agreed=19, cases=20)

        assert bound == pytest.approx(NINETEEN_OF_TWENTY, abs=1e-9)
        assert f"{bound:.1%}" == "76.4%"

    def test_a_larger_sample_at_the_same_rate_earns_a_tighter_bound(self):
        """Row 3: the one where a bigger sample earns a tighter bound.

        38 of 40 is the 95% that 19 of 20 is. A bound computed from the ratio
        alone would give both the same figure; it is the count that tightens it.
        """
        bound = lower_bound(agreed=38, cases=40)

        assert bound == pytest.approx(THIRTY_EIGHT_OF_FORTY, abs=1e-9)
        assert f"{bound:.1%}" == "83.5%"
        assert bound > lower_bound(agreed=19, cases=20)

    def test_a_bound_is_never_above_the_agreement_it_bounds(self):
        """Every row: a lower bound above the figure it bounds would be no bound."""
        for agreed, cases in ((20, 20), (19, 20), (38, 40), (12, 20), (1, 20)):
            assert 0.0 <= lower_bound(agreed=agreed, cases=cases) < agreed / cases

    def test_a_count_that_is_not_a_sample_is_refused(self):
        """No sample, or more agreed than cases: a caller's mistake, not a figure."""
        with pytest.raises(ValueError):
            lower_bound(agreed=0, cases=0)
        with pytest.raises(ValueError):
            lower_bound(agreed=21, cases=20)

    def test_the_bound_gates_nothing(self):
        """Row 4, counter-example: the one where the bound is reported and gates nothing.

        R7.11's judge measured 20 of 20 against a bar of 0.95. Its bound is below
        that bar, and it is still reported: R7.5 compares the agreement, and what
        the bar should compare is a threshold nobody has agreed yet.
        """
        measured = Calibration(
            judge_model="openai:gpt-5.4-mini",
            rubric_hash="f7a2d9c4",
            prompt_hash="0443845a",
            agreement=1.0,
            sample_size=20,
        )

        assert lower_bound(agreed=20, cases=20) < 0.95
        assert (
            withholding(
                measured,
                judge_model="openai:gpt-5.4-mini",
                rubric_hash="f7a2d9c4",
                prompt_hash="0443845a",
                threshold=0.95,
            )
            is None
        )
