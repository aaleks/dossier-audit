"""R7.15 — `dossier eval` withholds a judged field whose calibration is missing,
short or stale. The decision.

The acceptance test beside this one proves the command withholds and says why;
this proves the *why* is decided once, in order, from a calibration and four
strings -- no workspace, no files. Each state names a different fix, so each is
told apart rather than all reading as "no score".
"""

from __future__ import annotations

from dossier.domain.judges import Calibration, withholding

JUDGE = "anthropic:claude-sonnet-4-5-20250929"
OTHER_JUDGE = "anthropic:claude-opus-4-1-20250805"
RUBRIC = "f7a2d9c4" * 8
PROMPT = "0e52dd18" * 8
BAR = 0.95


def _measured(*, agreement: float = 0.95, judge: str = JUDGE, sample: int = 20) -> Calibration:
    return Calibration(
        judge_model=judge,
        rubric_hash=RUBRIC,
        prompt_hash=PROMPT,
        agreement=agreement,
        sample_size=sample,
    )


def _why(calibration: Calibration | None, *, judge: str = JUDGE, threshold=BAR) -> str | None:
    return withholding(
        calibration,
        judge_model=judge,
        rubric_hash=RUBRIC,
        prompt_hash=PROMPT,
        threshold=threshold,
        threshold_file="judge.yaml",
    )


class TestWhyAJudgedFieldIsWithheld:
    """R7.15 — four states, four fixes, told apart."""

    def test_below_the_bar_names_the_figure_and_the_bar(self):
        """Example 1: the one measured at 0.91 against a declared 0.95 (R7.5)."""
        reason = _why(_measured(agreement=0.91))

        assert reason is not None and "0.91" in reason and "0.95" in reason

    def test_a_stale_calibration_says_which_half_moved(self):
        """Example 2: the one measured against a judge nobody is using now (R7.6)."""
        reason = _why(_measured(judge=OTHER_JUDGE))

        assert reason is not None and "stale" in reason and OTHER_JUDGE in reason

    def test_a_moved_rubric_is_the_half_named(self):
        """Example 2's other half: the one where the rubric moved, either way its hash sorts."""
        for measured, current in (("0" * 64, RUBRIC), ("f" * 64, RUBRIC)):
            calibration = _measured().model_copy(update={"rubric_hash": measured})
            reason = withholding(
                calibration,
                judge_model=JUDGE,
                rubric_hash=current,
                prompt_hash=PROMPT,
                threshold=BAR,
            )

            assert reason == "calibration is stale: the rubric has changed since"

    def test_a_short_calibration_is_not_measurable(self):
        """Example 8: the one measured on 12 cases, where 20 is the minimum (R7.11 row 3)."""
        reason = _why(_measured(sample=12))

        assert reason is not None
        assert reason.startswith(
            "agreement was measured on 12 case(s), and 20 is the minimum at which the "
            "figure means anything."
        )

    def test_never_measured_asks_for_a_calibration(self):
        """Example 3: the one with no calibration file at all."""
        reason = _why(None)

        assert reason is not None and "never measured" in reason and "calibrate" in reason

    def test_exactly_at_the_bar_is_reported(self):
        """Example 4: the one where the bound is inclusive (R7.5 row 3)."""
        assert _why(_measured(agreement=0.95)) is None

    def test_no_declared_bar_names_the_file(self):
        """R7.13 row 5's shape: the one whose threshold file says nothing about the field."""
        reason = _why(_measured(), threshold=None)

        assert reason is not None and "judge.yaml" in reason

    def test_stale_is_decided_before_the_bar(self):
        """The order: a figure measured against something else is not compared with anything.

        Stale *and* below the bar reports stale; the bar is a question about
        this judge's figure, and a stale one is not this judge's.
        """
        reason = _why(_measured(agreement=0.5, judge=OTHER_JUDGE))

        assert reason is not None and "stale" in reason and "below" not in reason
