"""R6.3 — every non-null field carries a source naming a document that is an
input to that stage.

A citation to a document the stage never read is worse than no citation, because
it looks checkable.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from tests.grounding_fixtures import LOSS_SPAN, PROCEDURE_SPAN, STAGE_INPUTS

from dossier.domain.grounding import FieldVerdict, check_field
from dossier.domain.schemas import Evidence, FieldRecord


def loss_amount(document: str) -> FieldRecord:
    return FieldRecord(
        field="loss_amount",
        value=48200.00,
        currency="CHF",
        source=Evidence(document=document, span=LOSS_SPAN, page=3),
    )


class TestSourceNamesAnInput:
    """R6.3 — a citation must be to something this stage actually read."""

    def test_citing_a_documents_input_is_accepted(self):
        """Example 1: the one where the field cites the document it came from."""
        check = check_field(loss_amount("INC-4821"), input_documents=STAGE_INPUTS)

        assert check.verdict is FieldVerdict.VALID

    def test_citing_a_document_this_stage_never_read_is_invalid(self):
        """Example 2: the one where the citation is fiction.

        Invalid rather than ungrounded, and the distinction matters: an
        ungrounded field cited something real and got the quote wrong, while this
        one cited a document that was never in the room.
        """
        check = check_field(loss_amount("INC-9999"), input_documents=STAGE_INPUTS)

        assert check.verdict is FieldVerdict.INVALID
        assert "INC-9999" in check.detail

    def test_citing_a_reference_input_is_accepted(self):
        """Example 3: the one where the evidence is in a procedure.

        Reference documents are inputs like any other. `verify` reads the
        original alongside the procedure, and a field may cite either.
        """
        check = check_field(
            FieldRecord(
                field="review_required",
                value=True,
                source=Evidence(document="OPS-114", span=PROCEDURE_SPAN),
            ),
            input_documents=STAGE_INPUTS,
        )

        assert check.verdict is FieldVerdict.VALID

    def test_an_abstaining_field_needs_no_source(self):
        """Counter-example (row 4): the one where there is nothing to evidence."""
        check = check_field(
            FieldRecord(field="root_cause", value=None, reason="not stated in document"),
            input_documents=STAGE_INPUTS,
        )

        assert check.verdict is FieldVerdict.ABSTAINED

    def test_the_error_lists_the_inputs_that_were_available(self):
        """The one where the message is actionable rather than merely correct.

        R3.1's principle applied to a runtime verdict: naming what the stage did
        read turns "wrong document" into "you meant this one".
        """
        check = check_field(loss_amount("INC-9999"), input_documents=STAGE_INPUTS)

        assert "INC-4821" in check.detail
        assert "OPS-114" in check.detail
