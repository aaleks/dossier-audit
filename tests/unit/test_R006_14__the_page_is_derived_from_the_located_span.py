"""R6.14 — `source.page` is derived from the located span.

The field record has carried a `page` since the shape was written, and until this
rule nothing ever checked it: the model asserted a number and no code disagreed.
The page becomes an output of grounding rather than an input to it.

The rows below are the rule's example table, transcribed. `INC-4821`'s converted
text is built here with anchors rather than read from a fixture, because the
claim is about the derivation and not about any one converter's output.
"""

from __future__ import annotations

from dossier.domain.grounding import page_anchor, page_of_span, split_pages

# `INC-4821` as three anchored pages. The figure is on page 3, which is what
# `specs/_fixtures.md` records for it.
PAGES = [
    "INC-4821 Checkout incident\nOpened 2026-07-28.",
    "Timeline\n08:14 first alert\n09:48 recovered.",
    "Financial impact\ntotal exposure CHF 48'200 across the window.",
]
ANCHORED = "".join(f"{page_anchor(n)}\n{text}\n" for n, text in enumerate(PAGES, 1))

# A markdown note: real converted text, and no pages anywhere in it.
UNPAGED = "# INC-4821\n\nTotal exposure CHF 48'200 on the day.\n"


class TestThePageIsReadFromTheDocument:
    """R6.14 — the anchor the span landed after, or nothing."""

    def test_a_span_on_the_third_page_cites_the_third_page(self):
        """Example 1: the one where the number is read, not asserted."""
        assert page_of_span("total exposure CHF 48'200", document_text=ANCHORED) == 3

    def test_the_first_page_is_one_and_not_zero(self):
        """The boundary: the one where an off-by-one would be invisible.

        A reader turns to page 1, not page 0. Worth its own row because every
        other assertion here would pass against an index.
        """
        assert page_of_span("Opened 2026-07-28", document_text=ANCHORED) == 1

    def test_a_document_with_no_anchors_cites_no_page(self):
        """Example 3: the one where there are no pages to number.

        `None`, not `1`. A markdown note has no pages, and a fabricated `1`
        would be the same lie in a smaller font -- an auditor would trust it
        exactly as much as a real one.
        """
        assert page_of_span("Total exposure CHF 48'200", document_text=UNPAGED) is None

    def test_a_span_that_is_not_there_cites_no_page(self):
        """Example 4: the one where there is no evidence to have a page.

        R6.4 marks the field ungrounded. A page here would be provenance for a
        claim that has none, which is the failure mode this rule exists to close.
        """
        assert page_of_span("total exposure CHF 90'000", document_text=ANCHORED) is None

    def test_an_empty_span_cites_no_page(self):
        """Counter-example: the one where nothing was claimed.

        An empty string is a substring of every document, and `locate_span`
        already refuses it for that reason (R6.6). The page must refuse it on
        the same grounds rather than answering `1` because the first anchor
        precedes position zero.
        """
        assert page_of_span("", document_text=ANCHORED) is None

    def test_whitespace_is_normalised_on_both_sides_as_R6_4_does(self):
        """The one where the converter flattened a line the model quoted whole.

        Grounding normalises both sides before searching (R6.4 row 2). The page
        derivation searches the same text, so it must agree with it -- a span
        that grounds and then has no page would be the two halves disagreeing.
        """
        assert page_of_span("total  exposure   CHF 48'200", document_text=ANCHORED) == 3


class TestTheAnchorIsAContractBetweenLayers:
    """R6.14 — the format a converter writes is the one grounding reads."""

    def test_the_pages_split_back_out_of_the_text_that_holds_them(self):
        """The one where a converter's pages survive the round trip.

        `split_pages` is the inverse of what a converter did. Nothing in a run
        needs it, but a test and a converter author both do, and defining it
        once here is what stops the format being written down twice.
        """
        assert len(split_pages(ANCHORED)) == 3
        assert "CHF 48'200" in split_pages(ANCHORED)[2]

    def test_text_with_no_anchors_is_one_page_worth_of_text(self):
        """Counter-example: the one where there was never a page boundary.

        One element, not zero and not an error: the caller asked to split text
        that has no splits in it, and the honest answer is the text.
        """
        assert split_pages(UNPAGED) == [UNPAGED]

    def test_an_anchor_is_not_something_a_document_would_say(self):
        """The one that keeps the format from being guessable prose.

        An HTML comment: invisible wherever the artifact is rendered, and not
        something PDF text extraction produces. If this were a bare line like
        `Page 3` then every document with a printed footer would carry false
        anchors, and the page would be derived from the wrong thing.
        """
        assert page_anchor(3) == "<!-- page 3 -->"
        assert page_of_span("Page 3 of 12", document_text="Page 3 of 12") is None
