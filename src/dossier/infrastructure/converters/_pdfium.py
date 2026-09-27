"""PDFium, drawing with the fonts it carries and none that the machine has (R8.28).

A PDF that does not embed its fonts names them, and leaves finding them to
whatever reads it. PDFium asks the machine: on Windows it drew `INC-4830`'s
Helvetica with Arial, and on a Linux image with no fonts it used the ones built
into PDFium. A tenth of the pixels differed, and so did what Docling's layout
model read from them -- two artifacts under one `K_convert` (spec 008, open
question 2), which R8.1 row 3 names as a font file outside the input.

`FPDF_SetSystemFontInfo(None)` takes the machine's fonts away from PDFium, which
then draws every font a PDF does not embed with the fonts inside the pinned
`pypdfium2` wheel -- the same bytes on every machine. It is process-wide, so it
is done once, before any document is opened: a font PDFium had already looked
up on the machine could be kept for the next document.
"""

from __future__ import annotations

import threading
from types import ModuleType

_lock = threading.Lock()
_fonts_are_pdfiums_own = False


def pdfium() -> ModuleType:
    """`pypdfium2`, with PDFium drawing only with its own fonts.

    Raises `ImportError` without the `pdf` extra, which each converter turns into
    its own message naming the extra.
    """
    import pypdfium2
    import pypdfium2.raw as raw

    global _fonts_are_pdfiums_own
    with _lock:
        if not _fonts_are_pdfiums_own:
            raw.FPDF_SetSystemFontInfo(None)
            _fonts_are_pdfiums_own = True
    return pypdfium2
