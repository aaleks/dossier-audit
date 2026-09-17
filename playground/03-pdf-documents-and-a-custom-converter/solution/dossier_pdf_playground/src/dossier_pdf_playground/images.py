"""`application/pdf` read as the `page_images` kind: the images the pages carry.

The second half of what a pair means (R8.3). Media type cannot express that one
PDF is wanted as text and another as images, and a declared kind cannot say what
the bytes are -- so the converter is registered against both, and one snapshot
can produce two artifacts under two kinds with two keys.

Only the `markdown` kind becomes text a stage reads and grounds spans in
(R6.4, `dossier.application.convert.MARKDOWN`). This artifact is a cache entry
with a provenance record: a `dossier convert` counts it, a `dossier run` keys it,
and no stage is shown it. That is a real position in the design, not a limitation
of this exercise -- page images arrive as an addition to text, never instead of it.
"""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Mapping

from pypdf import PdfReader


class PdfPageImagesConverter:
    """Every image embedded in a PDF, page by page, as a JSON index.

    JSON rather than a directory of files, because an artifact is one byte string
    addressed by one key. Sorted keys and a fixed separator, so the same PDF
    produces the same bytes on every machine -- an artifact whose bytes depended
    on dict ordering would fork every key above it (R5.6).
    """

    id = "pdf-page-images"
    version = "0.1.0"
    media_type = "application/pdf"
    kind = "page_images"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        try:
            reader = PdfReader(io.BytesIO(payload))
        except Exception as error:
            raise ValueError(f"{self.id} could not read the PDF: {error}") from error

        pages = []
        for number, page in enumerate(reader.pages, start=1):
            images = [
                {
                    "name": image.name,
                    "bytes": len(image.data),
                    # Base64 rather than raw, because the artifact is JSON. The
                    # image bytes are whatever the PDF embedded, unmodified: this
                    # converter extracts, it does not re-encode (R8.1).
                    "content_base64": base64.b64encode(image.data).decode("ascii"),
                }
                for image in page.images
            ]
            pages.append({"page": number, "images": images})

        return json.dumps(
            {"pages": pages}, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
