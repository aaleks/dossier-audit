"""PDF in, text out (spec 008).

The converter that makes a PDF-heavy corpus readable at all. Until it shipped,
`dossier` recognised `application/pdf` in `MEDIA_TYPES` and nothing claimed the
pair, so every postmortem in `tests/fixtures/documents/postmortems/pdf/` stopped
the run it was pointed at.

Ships in this package through the same entry-point group a third party would
use, with no special case -- which is exactly what R8.7 counter-example 3
permits. It is behind the `pdf` extra because PDFium is a large wheel with its
own release cadence, and pinning every installation of `dossier` to it is the
coupling R8.7 exists to avoid.

**What this converter does not do.** It reads the text layer. A scanned page has
none, and the artifact is then its anchors and nothing else -- correctly, and
visibly: that is what `dossier convert` is for (spec 008, "The command"), and it
is the case OCR and a vision step exist to answer. An empty text layer is not a
conversion failure, so it does not raise: the document converted, and what it
contains is the finding.
"""

from __future__ import annotations

from collections.abc import Mapping

from dossier.domain.grounding import page_anchor
from dossier.infrastructure.converters._pdfium import pdfium as load_pdfium

# Between one page's text and the next page's anchor. A blank line, because the
# artifact is text a stage reads and a span is searched in (R6.4) -- not a
# structured document.
PAGE_SEPARATOR = "\n\n"


class PdfMarkdownConverter:
    """`application/pdf` to the `markdown` kind, via its text layer."""

    id = "pdf-markdown"
    # Raise this whenever output could change for the same input. Nothing can
    # enforce that; it is the one promise a converter author makes by hand, and
    # R5.4 is what it buys.
    #
    # It covers the *pinned* PDFium too. pypdfium2 is a pinned dependency
    # precisely so that its extraction is part of what this version describes;
    # widening that pin without raising this leaves a cache full of artifacts
    # claiming to be something they are not.
    #
    # 1.1.0 -- every page is introduced by its anchor, so `source.page` is derived
    # from the document rather than asserted by the model (R6.14). Output changed
    # for the same input, which is precisely when this moves: R5.4 then
    # re-converts every PDF and leaves every other converter's artifacts alone.
    version = "1.1.0"
    media_type = "application/pdf"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """Every page's text layer, in page order, each behind its own anchor.

        `pypdfium2` is imported here rather than at module scope so that the
        entry point loads -- and `check_declared` can read this class's four
        attributes -- on an installation without the `pdf` extra. A converter
        that cannot be listed cannot be reported as claiming a pair, and an
        unclaimed pair's message (R8.24, R8.25) would then be missing the very
        converter that answers it.
        """
        try:
            # Drawing with PDFium's own fonts, never the machine's (R8.28).
            pdfium = load_pdfium()
        except ImportError as error:  # pragma: no cover - depends on the install
            raise ValueError(
                f"{self.id} needs the 'pdf' extra: install dossier[pdf]"
            ) from error

        try:
            document = pdfium.PdfDocument(payload)
            pages = [page.get_textpage().get_text_bounded() or "" for page in document]
        except Exception as error:
            # R8.6's shape: one document fails with a reason and the others
            # convert. An encrypted or truncated PDF is a bad input, not a
            # misconfigured pipeline (R8.24).
            raise ValueError(f"{self.id} could not read this PDF: {error}") from error

        # The anchor is what makes `source.page` a derived fact rather than a
        # claim (R6.14). Its format is `domain`'s and is imported rather than
        # spelled again here: a converter writing one spelling while grounding
        # reads another is exactly the divergence that sharing one definition
        # avoids.
        #
        # PDFium emits CRLF; the text is normalised to LF. This converter
        # *generates* its artifact rather than passing one through, so it gets one
        # line-ending convention -- the alternative leaks a PDF library's detail
        # into every span a stage quotes back (R6.4).
        text = PAGE_SEPARATOR.join(
            f"{page_anchor(number)}\n{page.replace(chr(13) + chr(10), chr(10))}".rstrip()
            for number, page in enumerate(pages, 1)
        )
        return text.encode("utf-8")
