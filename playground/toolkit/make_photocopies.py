#!/usr/bin/env python3
"""Write the playground's photocopies: a PDF whose pages are pictures of pages.

    python playground/toolkit/make_photocopies.py --out playground/work/23/inbox/scans

Exercise 23 runs over these. They are made on demand rather than kept in
`corpus/`, as the tests' are: four pages of pictures weigh more than every other
playground document together. A photocopy is what OCR exists for: every page is a
picture, and there is no text layer for a converter to read. They are made from
`corpus/observability/PLAY-3005-weekly-incident-review.pdf`, which is born
digital. So what OCR reads back can be compared, word for word, with the text
layer it was photographed from.

  PLAY-3007-weekly-review-photocopied.pdf       every page a picture
  PLAY-3008-weekly-review-half-photocopied.pdf  page 1 as published, pages 2-4
                                                pictures: a document someone
                                                printed half of and scanned back

Each copied page is drawn at 200 dpi in grey, and nothing else of it is kept:
no text layer, no fonts, no vector drawing. That is what a desk scanner gives
back, and the resolution the tests' photocopies use (`tests/scans.py`).

Reproducible, like the other generators here. PDFium draws with its own fonts
and never the machine's (R8.28), Pillow writes the pictures with no date, and
pypdf writes the objects in a fixed order. Running this twice gives identical
files. Needs the `pdf` extra and the dev group (`uv sync --all-extras`).
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
PUBLISHED = CORPUS / "observability" / "PLAY-3005-weekly-incident-review.pdf"
DPI = 200

COPIES = {
    # name: the pages kept as published, 1-based; every other page is a picture
    "PLAY-3007-weekly-review-photocopied.pdf": (),
    "PLAY-3008-weekly-review-half-photocopied.pdf": (1,),
}


def photocopy(pdf: bytes, *, keep: tuple[int, ...]) -> bytes:
    """`pdf` with every page not in `keep` replaced by a picture of it."""
    from pypdf import PdfReader, PdfWriter

    # dossier's own PDFium loader, so the pages are drawn with PDFium's fonts on
    # every machine. A photocopy drawn with this machine's Arial would be
    # another file on the next machine, and so another snapshot.
    from dossier.infrastructure.converters._pdfium import pdfium

    rendered = pdfium().PdfDocument(pdf)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args(argv)

    arguments.out.mkdir(parents=True, exist_ok=True)
    published = PUBLISHED.read_bytes()
    for name, keep in COPIES.items():
        path = arguments.out / name
        path.write_bytes(photocopy(published, keep=keep))
        print(f"{path}  {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
