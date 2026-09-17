"""R7.6 — a stale judge calibration is an error, not a warning.

Agreement is re-measured whenever the judge model or its rubric changes. A
calibration measured against a different judge is not a calibration.

An error rather than a warning because of how the mistake is made. Nobody
deliberately reports a figure earned by a different model; they change the pinned
judge for a good reason, the old number is still sitting there, and every report
after that quotes a measurement of something that no longer runs. A warning is
read once and then scrolls past; a refusal is read every time.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from dossier.domain.judges import Calibration, is_stale

JUDGE = "anthropic:claude-sonnet-4-5-20250929"
OTHER_JUDGE = "anthropic:claude-opus-4-1-20250805"
RUBRIC = "0e52dd18" * 8
OTHER_RUBRIC = "b81f0c6d" * 8
PROMPT = "d24c86e1" * 8


def calibrated(*, judge: str = JUDGE, rubric: str = RUBRIC, sample: int = 20):
    return Calibration(
        judge_model=judge,
        rubric_hash=rubric,
        prompt_hash=PROMPT,
        agreement=0.91,
        sample_size=sample,
    )


class TestACalibrationBelongsToOneJudge:
    """R7.6 — measured against something else is not measured."""

    def test_a_changed_judge_model_makes_it_stale(self):
        """Example 1: the one where the pinned judge moved.

        The figure was earned by a model that is no longer being run. Whatever
        it says about the new one is unknown, and unknown is not 0.91.
        """
        assert (
            is_stale(
                calibrated(), judge_model=OTHER_JUDGE, rubric_hash=RUBRIC, prompt_hash=PROMPT
            )
            is True
        )

    def test_a_changed_rubric_makes_it_stale(self):
        """Example 2: the one where the question changed, not the model.

        A rubric is what the judge was asked. Same model, different question,
        different answers -- and the agreement figure was measured on the old
        question.
        """
        assert (
            is_stale(
                calibrated(), judge_model=JUDGE, rubric_hash=OTHER_RUBRIC, prompt_hash=PROMPT
            )
            is True
        )

    def test_both_unchanged_is_not_stale(self):
        """Example 3: the one that proves the check is not simply always true.

        Without this row the rule is satisfied by refusing every judge forever,
        which would pass every other row in this file.
        """
        assert (
            is_stale(calibrated(), judge_model=JUDGE, rubric_hash=RUBRIC, prompt_hash=PROMPT)
            is False
        )

    def test_a_grown_sample_is_not_stale(self):
        """Counter-example (row 4): the one where more gold arrived.

        More data does not invalidate a measurement made on less. It invites a
        re-measure, which is a different thing from making the old figure wrong,
        and treating growth as staleness would punish exactly the behaviour the
        gold set wants to encourage.
        """
        measured_on_20 = calibrated(sample=20)

        assert (
            is_stale(measured_on_20, judge_model=JUDGE, rubric_hash=RUBRIC, prompt_hash=PROMPT)
            is False
        )

    def test_either_change_alone_is_enough(self):
        """The one that stops the check being an `and`.

        Written as "the judge model or its rubric", and an implementation
        joining the two with `and` would go stale only when both moved -- which
        is the case that almost never happens.
        """
        assert is_stale(
            calibrated(), judge_model=OTHER_JUDGE, rubric_hash=RUBRIC, prompt_hash=PROMPT
        )
        assert is_stale(
            calibrated(), judge_model=JUDGE, rubric_hash=OTHER_RUBRIC, prompt_hash=PROMPT
        )
        assert is_stale(
            calibrated(), judge_model=OTHER_JUDGE, rubric_hash=OTHER_RUBRIC, prompt_hash=PROMPT
        )

    def test_the_model_identifier_is_compared_exactly(self):
        """The one where a floating alias would slip through.

        R0.6 forbids an unpinned model identifier, so two pins that differ by
        their date are two different models. Comparing loosely -- by family, or
        by prefix -- would let a calibration survive the version change it exists
        to catch.
        """
        later_pin = "anthropic:claude-sonnet-4-5-20260101"

        assert (
            is_stale(
                calibrated(), judge_model=later_pin, rubric_hash=RUBRIC, prompt_hash=PROMPT
            )
            is True
        )
