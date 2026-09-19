"""R6.15 — a field citing a document the stage was shown as pictures is `described`.

R6.4's search is over converted text. A stage shown `page_images` has none, so
every field it produces fails the search and lands on `ungrounded` -- which says
"nothing in the document shows it" about a document that shows it plainly.

The distinction matters before anything else reads it: R7.4 scores an
`ungrounded` field incorrect before any comparison with gold, so the wrong
verdict here is a wrong figure in a report and nothing in between.
"""

from __future__ import annotations

import pytest

from dossier.domain.grounding import FieldVerdict, check_field
from dossier.domain.schemas import FieldRecord

CHART = "INC-5720-checkout-latency-postmortem.png"
NOTE = "INC-4821"

SPAN = "Total abandoned checkout value over the window:  CHF 132'400"

# The note's converted text, which says the same figure in a sentence. Used for
# the row where a stage shown pictures quotes something a search can still find.
NOTE_TEXT = f"The review put the {SPAN} against the quarter's budget."


def _record(document: str, span: str | None = SPAN) -> FieldRecord:
    return FieldRecord.model_validate(
        {
            "field": "loss_amount",
            "value": 132400.00,
            "currency": "CHF",
            "source": {"document": document, "span": span},
        }
    )


class TestAFieldReadOffAPictureIsDescribed:
    """R6.15 — the third grounding state, as a pure decision."""

    def test_a_value_quoted_from_a_page_image_is_described(self):
        """Example 1: the one the visual-evidence slice exists for.

        There is no text for this document at all, because it converted to
        pictures and to nothing else.
        """
        check = check_field(_record(CHART), input_documents={}, shown_as_pictures={CHART})

        assert check.verdict is FieldVerdict.DESCRIBED
        assert not check.is_failure, "described evidence exists; it is simply not searchable"

    def test_a_stage_that_had_text_to_search_is_unchanged(self):
        """Example 2: the one where nothing about R6.4 moves.

        Same record, same unfindable span, a stage shown the document as
        markdown. `ungrounded` is still the right answer and still a failure.
        """
        check = check_field(
            _record(NOTE), input_documents={NOTE: "nothing of the sort"}, shown_as_pictures=()
        )

        assert check.verdict is FieldVerdict.UNGROUNDED
        assert check.is_failure

    def test_a_span_that_locates_is_grounded_however_the_model_came_by_it(self):
        """Example 3: the one where better evidence wins.

        A model reading a rendered page can still quote the document verbatim.
        Demoting that to `described` would throw away a citation anyone can
        check, for no reason but the route it arrived by.
        """
        check = check_field(
            _record(NOTE), input_documents={NOTE: NOTE_TEXT}, shown_as_pictures={NOTE}
        )

        assert check.verdict is FieldVerdict.VALID

    def test_a_null_with_a_reason_is_still_an_abstention(self):
        """Counter-example 5: the one where a picture makes no claim.

        Being shown a page does not turn "not stated" into something to
        describe. R6.5 decides first, and keeps deciding.
        """
        record = FieldRecord.model_validate(
            {"field": "loss_amount", "value": None, "reason": "this page is the timeline"}
        )

        check = check_field(record, input_documents={}, shown_as_pictures={CHART})

        assert check.verdict is FieldVerdict.ABSTAINED
        assert not check.is_failure

    def test_citing_a_document_this_stage_never_saw_is_still_invalid(self):
        """Counter-example 6: the one where pictures excuse nothing.

        Being shown pictures of one document says nothing about another. A
        citation to a document the stage never read looks checkable and is not,
        which R6.3 calls worse than no citation at all.
        """
        check = check_field(_record(NOTE), input_documents={}, shown_as_pictures={CHART})

        assert check.verdict is FieldVerdict.INVALID
        assert "was not an" in (check.detail or "")

    @pytest.mark.parametrize("shown", [(), {CHART}])
    def test_an_empty_span_is_never_evidence(self, shown):
        """The boundary R6.4 already draws, held on both sides of the new one.

        An empty span is a substring of every document and of no picture. It
        must not become `described` simply because the stage saw a page -- that
        would make citing nothing the cheapest way to pass.
        """
        check = check_field(
            _record(CHART, span=""), input_documents={CHART: ""}, shown_as_pictures=shown
        )

        assert check.is_failure
