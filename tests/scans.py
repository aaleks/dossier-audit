"""Photocopies of a PDF, made on demand rather than committed (`specs/_fixtures.md`).

A photocopy is what OCR exists for: every page a picture, and no text layer for a
converter to read. Made from a committed, born-digital postmortem rather than
checked in, so that what OCR read back can be compared word for word with the
text layer it was photographed from -- and so that three pages of pictures do not
double the size of `tests/fixtures/`.

Each copied page is rendered at `DPI` in grey and written back as a picture of
the same size, and nothing else of it is kept: no text layer, no fonts, no
vector drawing. A page listed in `keep` is copied as published instead, which is
what a half-photocopied document is.
"""

from __future__ import annotations

import io
from collections.abc import Collection

# What a desk scanner produces for a document meant to be read back, and what the
# spike that preceded spec 008's Docling rules measured at (R8.14).
DPI = 200


def photocopy(pdf: bytes, *, keep: Collection[int] = ()) -> bytes:
    """`pdf` with every page not in `keep` (1-based) replaced by a picture of it."""
    import pypdfium2 as pdfium
    from pypdf import PdfReader, PdfWriter

    rendered = pdfium.PdfDocument(pdf)
    published = PdfReader(io.BytesIO(pdf))
    copy = PdfWriter()

    for number, page in enumerate(published.pages, 1):
        if number in keep:
            copy.add_page(page)
            continue
        picture = rendered[number - 1].render(scale=DPI / 72).to_pil().convert("L")
        single = io.BytesIO()
        picture.save(single, "PDF", resolution=DPI)
        copy.add_page(PdfReader(single).pages[0])

    written = io.BytesIO()
    copy.write(written)
    return written.getvalue()
