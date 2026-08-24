"""R6.4 — a span that cannot be located in the named document marks it ungrounded.

After whitespace normalisation, and by string search alone. No judgement, no
model, no cost.

The rows below are the rule's example table, transcribed. The document text is
the fixture incident report, which is why the span reads the way it does.
"""

from __future__ import annotations

import pytest

from dossier.domain.grounding import locate_span, normalise_whitespace

CONVERTED = (
    "# INC-4821 - Payment batch partially rejected\n"
    "\n"
    "## Impact\n"
    "\n"
    "Finance confirmed a total exposure CHF 48'200 in late-settlement interest\n"
    "and manual reprocessing effort.\n"
)


class TestLocateSpan:
    """R6.4 — the quoted sentence is either in the document or it is not."""

    def test_a_span_present_in_the_text_is_grounded(self):
        """The one where the model quoted the document correctly.

        Example 1.
        """
        assert locate_span("total exposure CHF 48'200", document_text=CONVERTED)

    def test_whitespace_is_normalised_on_both_sides(self):
        """Example 2: the one where the span has a doubled space and the text does not.

        Both sides are normalised, not just the span. A converter that collapsed
        a table into running text is as likely to be the source of the
        difference as the model is.
        """
        assert locate_span("total  exposure   CHF 48'200", document_text=CONVERTED)

    def test_a_span_crossing_a_line_break_is_grounded(self):
        """The one that makes normalisation earn its keep.

        The document wraps mid-sentence. A model quoting the sentence has no way
        to know where the line broke, and failing it for that would make the
        check useless on any real converted text.
        """
        assert locate_span(
            "in late-settlement interest and manual reprocessing effort",
            document_text=CONVERTED,
        )

    def test_a_plausible_but_absent_span_is_ungrounded(self):
        """Example 3: the one where the value is right and the evidence is not.

        `48,200` instead of `48'200`. The extracted value would be correct and
        the citation is to something the document never said, which R7.4 scores
        as incorrect regardless.
        """
        assert not locate_span("total exposure CHF 48,200", document_text=CONVERTED)

    def test_an_empty_span_is_never_grounded(self):
        """The boundary that would otherwise ground everything.

        An empty string is a substring of every document. Treating it as located
        would let a field cite nothing and pass the check, which is the one
        outcome that makes grounding decorative (R6.6).
        """
        assert not locate_span("", document_text=CONVERTED)
        assert not locate_span("   ", document_text=CONVERTED)

    def test_a_span_is_not_located_in_an_empty_document(self):
        """The one where conversion produced nothing.

        A page-image-only PDF converts to no text. Every span then fails, which
        is correct: nothing can be evidenced against a document nobody can read.
        """
        assert not locate_span("total exposure", document_text="")

    def test_the_search_is_case_sensitive(self):
        """The one where a quote is a quote.

        Deliberately strict. Case-folding would let `MAJOR` cite a document
        saying `major`, and a span is supposed to be what the document says --
        not an approximation of it. If this proves too strict against real
        converted text, it is a spec conversation, not a quiet relaxation.
        """
        assert not locate_span("TOTAL EXPOSURE CHF 48'200", document_text=CONVERTED)

    def test_a_non_breaking_space_matches_an_ordinary_one(self):
        """The one that comes straight from PDF conversion.

        PDF text extraction routinely emits U+00A0 inside figures like
        `CHF 48'200`. A reader cannot see the difference and neither should the
        check.
        """
        assert locate_span("total exposure\xa0CHF 48'200", document_text=CONVERTED)


class TestNormaliseWhitespace:
    """The normalisation itself, since both sides depend on it."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param("a  b", "a b", id="doubled-space"),
            pytest.param("a\nb", "a b", id="newline"),
            pytest.param("a\t\tb", "a b", id="tabs"),
            pytest.param("  a b  ", "a b", id="leading-and-trailing"),
            pytest.param("a\xa0b", "a b", id="non-breaking-space"),
            pytest.param("", "", id="empty"),
        ],
    )
    def test_runs_of_whitespace_become_one_space(self, raw: str, expected: str):
        assert normalise_whitespace(raw) == expected

    def test_normalisation_is_idempotent(self):
        """The one where applying it twice changes nothing.

        Both the span and the document go through it, sometimes more than once
        as text moves between stages. A normalisation that drifted on a second
        pass would make grounding depend on how many times it had been called.
        """
        once = normalise_whitespace("  a \n\n b  ")

        assert normalise_whitespace(once) == once
