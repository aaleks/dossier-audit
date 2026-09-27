"""PDF in, one picture per page out (spec 008).

The other half of what `dossier[pdf]` installs, and the kind that exists for the
documents `pdf-markdown` cannot help with: a scan with no text layer, a chart
whose value is drawn rather than written, a screenshot pasted into a report.

The artifact is one container holding one PNG per page (R8.11), not one artifact
per page. R8.4 says a declared conversion is one artifact with one key, and
forty keys for a forty-page PDF would let R5.4 invalidate a document's pages
separately -- leaving a document with nineteen old pages and twenty-one new ones,
which no rule anywhere describes.

**No model is reached here.** A converter is a pure function of bytes and options
(R8.1) and sits right of the hash boundary (R0.10). Rendering a page is
arithmetic; *interpreting* what is on it is a model call, and that belongs to a
step whose key holds a model id and a prompt (spec 005, spec 009).
"""

from __future__ import annotations

from collections.abc import Mapping

from dossier.domain.conversion import pack_parts
from dossier.infrastructure.converters._pdfium import pdfium as load_pdfium
from dossier.infrastructure.converters._png import png

# Rendering scale, as a multiple of the PDF's own 72 dpi. 2.0 is 144 dpi: enough
# for a vision model to read an axis label on a chart, and small enough that a
# forty-page container is megabytes rather than tens of them.
#
# It is *not* an option, deliberately. An option would be in the key (R8.1),
# which is correct, but it would also let two pipelines in one workspace hold two
# renderings of the same page and quietly compare findings drawn from different
# pictures. If it ever becomes an option it arrives with a rule saying which one
# a report is showing.
SCALE = 2.0

PART_SUFFIX = ".png"


class PdfImagesConverter:
    """`application/pdf` to the `page_images` kind, one PNG per page."""

    id = "pdf-images"
    # Raise this whenever output could change for the same input. That covers
    # SCALE above, the pinned PDFium underneath and the pinned `deflate` that
    # compresses each page (R8.29): all decide what the bytes are, and none can
    # be discovered from the artifact afterwards. 1.1.0: pages written by `_png`,
    # not Pillow's encoder, whose bytes differed between Windows and Linux.
    # 1.2.0: drawn with PDFium's own fonts, not the machine's (R8.28).
    version = "1.2.0"
    media_type = "application/pdf"
    kind = "page_images"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """Every page rendered, packed in page order into one container.

        Imported here rather than at module scope so the entry point loads on an
        installation without the `pdf` extra -- the same reasoning as
        `pdf-markdown`, and for the same benefit to an unclaimed pair's message
        (R8.24, R8.25).
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
            pages = [self._render(page, scale=SCALE) for page in document]
        except Exception as error:
            # R8.6's shape: one document fails with a reason and the others
            # convert. An encrypted or truncated PDF is a bad input, not a
            # misconfigured pipeline (R8.24).
            raise ValueError(f"{self.id} could not render this PDF: {error}") from error

        return pack_parts(pages, suffix=PART_SUFFIX)

    @staticmethod
    def _render(page: object, *, scale: float) -> bytes:
        """One page as PNG bytes, written by `_png` rather than Pillow's encoder.

        Pillow's bytes depend on the zlib its wheel was built with, and a
        Windows wheel and a Linux wheel wrote the same page differently (R8.29).
        """
        return png(page.render(scale=scale).to_pil())  # type: ignore[attr-defined]
