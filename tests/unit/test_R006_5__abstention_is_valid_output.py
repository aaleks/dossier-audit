"""R6.5 — `value: null` with a reason is valid output and is never counted as a
failure.

"Not stated" is an answer. A system that cannot say it will invent something
instead.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from tests.grounding_fixtures import STAGE_INPUTS

from dossier.domain.grounding import FieldVerdict, check_field
from dossier.domain.schemas import FieldRecord


class TestAbstention:
    """R6.5 — the answer the design deck calls first-class."""

    def test_null_with_a_reason_is_valid(self):
        """Example 1: the one where the document genuinely does not say."""
        check = check_field(
            FieldRecord(
                field="root_cause",
                value=None,
                reason="not stated in document",
                confidence="none",
            ),
            input_documents=STAGE_INPUTS,
        )

        assert check.verdict is FieldVerdict.ABSTAINED

    def test_abstention_is_not_a_failure(self):
        """Example 2: the one that keeps abstention off the failure count.

        An abstaining field is sent for human review, which is not the same as
        failing. If abstaining counted against a run the incentive would be to
        guess — the exact behaviour grounding exists to prevent.
        """
        check = check_field(
            FieldRecord(field="root_cause", value=None, reason="not stated"),
            input_documents=STAGE_INPUTS,
        )

        assert check.is_failure is False

    def test_null_without_a_reason_is_invalid(self):
        """Example 3: the one where abstention must say why.

        A bare null is indistinguishable from a field the model simply forgot,
        and a reviewer cannot tell those apart either.
        """
        check = check_field(
            FieldRecord(field="root_cause", value=None),
            input_documents=STAGE_INPUTS,
        )

        assert check.verdict is FieldVerdict.INVALID

    def test_an_empty_reason_does_not_count(self):
        """The boundary: the one where the field claims a reason and gives none."""
        check = check_field(
            FieldRecord(field="root_cause", value=None, reason=""),
            input_documents=STAGE_INPUTS,
        )

        assert check.verdict is FieldVerdict.INVALID

    def test_abstaining_where_gold_has_a_value_is_still_valid_output(self):
        """Counter-example (row 4): the one where valid and correct differ.

        Abstaining when the gold set records `48200.00` is well-formed output and
        a wrong answer. R7.3 scores it incorrect; R6.5 says it is not a
        *validation* failure. Two different questions about one field, and
        conflating them would either hide wrong answers or punish honesty.
        """
        check = check_field(
            FieldRecord(field="loss_amount", value=None, reason="figure not found in document"),
            input_documents=STAGE_INPUTS,
        )

        assert check.verdict is FieldVerdict.ABSTAINED
        assert check.is_failure is False
