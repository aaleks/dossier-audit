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
none, and the artifact is then near-empty -- correctly, and visibly: that is what
`dossier convert` is for (spec 008, "The command"), and it is the case OCR and a
vision step exist to answer. An empty text layer is not a conversion failure, so
it does not raise: the document converted, and what it contains is the finding.
"""

from __future__ import annotations

from collections.abc import Mapping

# The page separator. A blank line, because the artifact is text a stage reads
# and a span is searched in (R6.4) -- not a structured document. A marker
# carrying the page number is what R6.x will need to make `source.page` a
# derived fact rather than a claim, and adding one changes output for the same
# input, so it arrives with a raised version rather than quietly here.
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
    version = "1.0.0"
    media_type = "application/pdf"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """Every page's text layer, in page order, separated by a blank line.

        Imported here rather than at module scope so that the entry point loads
        -- and `check_declared` can read this class's four attributes -- on an
        installation that does not have the `pdf` extra. A converter that cannot
        be listed cannot be reported as claiming a pair, and R8.5's message
        would then be missing the very converter that answers it.
        """
        try:
            import pypdfium2 as pdfium
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
            # misconfigured pipeline (R8.5).
            raise ValueError(f"{self.id} could not read this PDF: {error}") from error

        # PDFium emits CRLF. Normalised to LF because this converter *generates*
        # its artifact rather than passing one through: a generated artifact gets
        # one line-ending convention, and the alternative leaks a PDF library's
        # detail into every span a stage quotes back (R6.4).
        text = PAGE_SEPARATOR.join(page.replace("\r\n", "\n") for page in pages)
        return text.encode("utf-8")
