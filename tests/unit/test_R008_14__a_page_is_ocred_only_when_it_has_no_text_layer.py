"""R8.14 — `docling-markdown` OCRs a page only when it has no text layer.

The decision is made over the text each page's layer holds, and is proved here
row by row without Docling: which pages are OCR'd is a rule, and a rule is
provable in milliseconds when it is a function of a list of strings. That
Docling then reads each page the way this decides is the integration test's
claim, and that the result is grounded is the acceptance test's.
"""

from __future__ import annotations

from dossier.domain.conversion import ocr_pages

# INC-4830's three pages as published: each opens with text, which is all the
# decision looks at.
PUBLISHED = [
    "Checkout unavailable in production — expired TLS certificate",
    "Time Actor Event 06:11:58 Certificate on lb-acq-01/02 expires.",
    "Sign-off: R. Bianchi (Head of Platform), 2026-08-05.",
]


class TestAPageIsOcredOnlyWhenItHasNoTextLayer:
    """R8.14 — a page with a text layer is read from it, and one with none by OCR."""

    def test_every_page_of_a_photocopy_is_ocred(self):
        """Row 1: the one where no page has a text layer."""
        assert ocr_pages(["", "", ""]) == [1, 2, 3]

    def test_only_the_photocopied_pages_of_a_half_photocopy_are_ocred(self):
        """Row 2: the one where page 1 kept its text layer and pages 2 and 3 did not."""
        assert ocr_pages([PUBLISHED[0], "", ""]) == [2, 3]

    def test_a_layer_of_nothing_but_whitespace_is_no_text_layer(self):
        """The one where the layer holds line breaks and a space and no word.

        What PDFium returns for a scanner's blank text layer. Reading it would
        be reading nothing, exactly, and calling that the page.
        """
        assert ocr_pages([PUBLISHED[0], "\r\n \t\n"]) == [2]

    def test_a_layer_of_unprintable_characters_is_no_text_layer(self):
        """The one where the layer holds only control characters.

        No printable character is the wording of the rule: a layer a reader
        cannot see is not text a span can be quoted from.
        """
        assert ocr_pages(["\x00\x02\x0c"]) == [1]

    def test_no_page_of_a_published_pdf_is_ocred(self):
        """Counter-example, row 5: the one where every page has a text layer."""
        assert ocr_pages(PUBLISHED) == []

    def test_one_printable_character_is_a_text_layer(self):
        """Counter-example: the one where a page's layer is only its page number.

        Read from that layer rather than OCR'd whole. Docling's own OCR still
        reads any picture on such a page; what this decides is only whether the
        layer is thrown away, and a layer with something in it never is.
        """
        assert ocr_pages(["3"]) == []
