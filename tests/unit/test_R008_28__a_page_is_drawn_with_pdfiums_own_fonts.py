"""R8.28 — a page is rendered with PDFium's built-in fonts, never with the fonts
the machine has.

`INC-4830`'s postmortem does not embed its fonts. PDFium drew them with Windows'
Arial on one machine and with its own built-in fonts on a Linux image that has
none, and a tenth of the pixels differed (spec 008, open question 2). The pinned
hashes below are the proof that crosses machines: this suite runs on Windows
where it is written and on Linux in CI, and a page drawn with the machine's
fonts cannot give both the same hash.

Row 2, `docling-markdown`, needs Docling's models and is `live`, in
`tests/integration/test_R008_14__a_photocopied_pdf_converts_to_text.py`'s
company; here it is the default suite's `pdf-images` and `pdf-markdown`.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

pytest.importorskip("pypdfium2", reason="the PDF converters need dossier[pdf]")
pytest.importorskip("deflate", reason="page images are written by libdeflate (R8.29)")

from dossier.infrastructure.converters._pdfium import pdfium  # noqa: E402
from dossier.infrastructure.converters.pdf_images import PdfImagesConverter  # noqa: E402
from dossier.infrastructure.converters.pdf_markdown import PdfMarkdownConverter  # noqa: E402

DOCUMENTS = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
PUBLISHED = DOCUMENTS / "postmortems" / "pdf" / "INC-4830-postmortem-checkout-tls-expiry.pdf"
PICTURE = DOCUMENTS / "scans" / "PLAY-2002-photocopy-no-text-layer.pdf"

# Measured on Windows 11 and in `python:3.12-slim` before they were written, and
# held by CI on Linux. Raising `pypdfium2` moves them, and `pdf-images`'s
# version with them (R5.4).
PAGES = "1b8cded747012d95d061a4d0b529fc1925b2133c199a938b31a4b3fd385296d0"
TEXT = "484a703f02e8f70243691762fbd2f020d3695b4b4b64401578101771dedb5d5b"
PICTURE_PAGES = "909e8956a6dbf3c98c1d103ec59f0dfa87909c9ac5712ceaa1da85fc4ca0cd6c"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestAPageIsDrawnWithPdfiumsOwnFonts:
    """R8.28 — no font the machine has reaches a page's pixels."""

    def test_a_postmortem_without_embedded_fonts_renders_the_same_everywhere(self):
        """Row 1: the one where Helvetica is not borrowed from Windows.

        Three pages, one `page_images` artifact, one hash, on Windows and on
        Linux. With the machine's fonts, Windows drew Arial and gave another.
        """
        assert sha(PdfImagesConverter().convert(PUBLISHED.read_bytes(), {})) == PAGES

    def test_the_text_layer_reads_the_same_as_it_always_did(self):
        """Row 3: the one where `pdf-markdown` draws nothing, and nothing moves.

        It reads a text layer. Taking the machine's fonts away changes no
        character of it, so its version stays where it was.
        """
        assert sha(PdfMarkdownConverter().convert(PUBLISHED.read_bytes(), {})) == TEXT

    def test_a_page_that_is_only_a_picture_draws_no_font(self):
        """Counter-example (row 4): the one where there is no text to draw."""
        assert sha(PdfImagesConverter().convert(PICTURE.read_bytes(), {})) == PICTURE_PAGES

    def test_the_machines_fonts_are_taken_away_before_any_document_opens(self):
        """The one where the switch is made once, for the process.

        PDFium's choice is process-wide and a font it has already looked up can
        be kept, so the switch is made on first use and every later call finds
        it made. Two calls return the one module.
        """
        assert pdfium() is pdfium()
