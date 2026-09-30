"""R7.19 — a calibration is stale when the judge prompt has changed since it was
measured.

The rubric is the pipeline author's and its hash is in the calibration (R7.14).
The wrapper dossier puts the rubric in -- the document, the claim, the output
format -- is dossier's, and until this rule it was in no hash: an edit to it
changed what every judge was asked while every calibration read as fresh, which
is exactly what R7.6 exists to notice.

The rows below are the rule's example table, transcribed. R7.6's own rows keep
proving the judge model and the rubric; this file proves the third input.
"""

from __future__ import annotations

from dossier.domain.judges import Calibration, is_stale

JUDGE = "anthropic:claude-sonnet-4-5-20250929"
RUBRIC = "f7a2d9c4" * 8
PROMPT = "0e52dd18" * 8
OTHER_PROMPT = "d24c86e1" * 8


def _measured(*, prompt: str | None) -> Calibration:
    return Calibration(
        judge_model=JUDGE,
        rubric_hash=RUBRIC,
        prompt_hash=prompt,
        agreement=0.95,
        sample_size=20,
    )


class TestAChangedJudgePromptMakesACalibrationStale:
    """R7.19 — measured under another prompt is measured against something else."""

    def test_an_edited_prompt_makes_it_stale(self):
        """Example 1: the one where the wrapper moved and nothing else did.

        The judge model and the rubric both match, which is exactly the case
        R7.6 could not see: the question changed without the author's file
        changing.
        """
        assert (
            is_stale(
                _measured(prompt=PROMPT),
                judge_model=JUDGE,
                rubric_hash=RUBRIC,
                prompt_hash=OTHER_PROMPT,
            )
            is True
        )

    def test_a_calibration_with_no_prompt_hash_is_stale(self):
        """Example 2: the one measured before the prompt was recorded at all.

        Measured under a prompt nobody recorded is not the same as measured
        under this one, and a file from before this rule reads as such rather
        than as fresh.
        """
        assert (
            is_stale(
                _measured(prompt=None),
                judge_model=JUDGE,
                rubric_hash=RUBRIC,
                prompt_hash=PROMPT,
            )
            is True
        )

    def test_eval_names_which_of_the_two_it_is(self):
        """Examples 1 and 2 as `dossier eval` words them: changed, or never recorded."""
        from dossier.domain.judges import withholding

        def reason(prompt: str | None) -> str | None:
            return withholding(
                _measured(prompt=prompt),
                judge_model=JUDGE,
                rubric_hash=RUBRIC,
                prompt_hash=OTHER_PROMPT,
                threshold=0.95,
            )

        assert (
            reason(PROMPT) == "calibration is stale: the judge prompt has changed since (R7.19)"
        )
        assert reason(None) == (
            "calibration is stale: measured under a judge prompt nobody recorded (R7.19)"
        )

    def test_nothing_moved_so_it_proceeds(self):
        """Counter-example (row 3): the one where rubric, model and prompt all match (R7.6)."""
        assert (
            is_stale(
                _measured(prompt=PROMPT),
                judge_model=JUDGE,
                rubric_hash=RUBRIC,
                prompt_hash=PROMPT,
            )
            is False
        )
