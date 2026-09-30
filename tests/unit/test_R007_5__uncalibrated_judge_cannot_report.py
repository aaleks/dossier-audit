"""R7.5 — a judge below its configured agreement threshold cannot be used as a
reported metric.

Given an agreement number, this is a gate with an exact answer. Producing the
number is R7.11's problem, and R7.11's threshold is deliberately still `OPEN` --
it needs at least twenty human-scored cases before a figure means anything, and
the figure is the domain expert's to agree rather than this module's to invent.

So this rule is built and the number it compares against is not. That is the
right order: the machinery has somewhere for the figure to go, and no number has
been quietly chosen on the way.

What the gate buys is honest silence. A judge that has not been shown to agree
with a human produces a percentage that reads exactly like evidence, and refusing
to print it is the only way to tell the two apart.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.judges import Calibration, NotCalibrated, is_eligible

JUDGE = "anthropic:claude-sonnet-4-5-20250929"
RUBRIC = "0e52dd18" * 8


def calibrated(agreement: float, *, sample_size: int = 20) -> Calibration:
    return Calibration(
        judge_model=JUDGE,
        rubric_hash=RUBRIC,
        agreement=agreement,
        sample_size=sample_size,
    )


class TestAJudgeMustEarnTheRightToBeQuoted:
    """R7.5 — above the bar it reports; below it, it says why instead."""

    def test_agreement_above_the_threshold_is_eligible(self):
        """Example 1: the one where the judge was shown to agree."""
        assert is_eligible(calibrated(0.91), threshold=0.85) is True

    def test_agreement_below_the_threshold_is_not(self):
        """Example 2: the one where a number would be worse than none.

        0.78 agreement means roughly one verdict in five disagrees with the
        person who signs off the gold set. A `root_cause 62.4%` printed from that
        reads like a measurement and is closer to a guess.
        """
        assert is_eligible(calibrated(0.78), threshold=0.85) is False

    def test_the_bound_is_inclusive(self):
        """Example 3: the one that is exactly on the line.

        Stated in the spec, and the kind of thing that gets implemented as `>`
        by accident. A judge measured at precisely the agreed figure has met the
        agreed figure.
        """
        assert is_eligible(calibrated(0.85), threshold=0.85) is True

    def test_a_field_with_no_judge_is_not_this_rule(self):
        """Counter-example (row 4): the one scored by exact match.

        `loss_amount` has no judge and no threshold, so there is nothing to
        gate. Asking this function about it is a category error, and returning
        `True` would quietly report a field as calibrated when nothing was
        measured.
        """
        with pytest.raises(NotCalibrated):
            is_eligible(None, threshold=0.85)

    def test_a_threshold_outside_zero_to_one_is_refused(self):
        """The one where the configured figure is not an agreement at all.

        Agreement is a proportion. A threshold of 85 rather than 0.85 would make
        every judge ineligible forever, and the run would look like a very
        strict configuration rather than a typo.
        """
        for bad in (-0.1, 1.5, 85):
            with pytest.raises(ValueError):
                is_eligible(calibrated(0.91), threshold=bad)
        # Both ends of the range are proportions: a bar of 1.0 asks for every
        # case, and one of 0.0 for none.
        assert is_eligible(calibrated(0.91), threshold=1.0) is False
        assert is_eligible(calibrated(0.91), threshold=0.0) is True

    def test_a_calibration_measured_on_too_small_a_sample_is_refused(self):
        """R7.11 row 3, enforced here: "not measurable at this N".

        Nineteen cases do not become twenty by being compared against a
        threshold. A figure from too small a sample is not a weak measurement,
        it is not a measurement, and the gate must not launder one into a pass.
        """
        with pytest.raises(NotCalibrated) as error:
            is_eligible(calibrated(0.95, sample_size=19), threshold=0.85)

        assert "19" in str(error.value)
