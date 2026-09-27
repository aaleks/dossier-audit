"""R8.28 row 2 — `docling-markdown` reads a page drawn with PDFium's own fonts.

Docling's default backend, docling-parse, drew `INC-4830`'s page 1 by matching
its unembedded Helvetica against the machine's font folders. Windows and Linux
gave its layout model different pixels, and the half-photocopy's artifact lost a
heading on one of them (spec 008, open question 2). Docling now reads a PDF
through its pypdfium2 backend, and PDFium draws with the fonts inside its wheel.

The hashes below were measured on Windows 11 and in `python:3.12-slim` before
they were written. CI does not run `live`, so this test is the second machine's
proof only where someone runs it there -- which is what a pinned hash is for.

`live`, because it needs `dossier[docling]` and the weights R8.15 names.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from tests.scans import photocopy

pytestmark = pytest.mark.live

PUBLISHED = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "documents"
    / "postmortems"
    / "pdf"
    / "INC-4830-postmortem-checkout-tls-expiry.pdf"
)

# `docling-markdown` 1.1.0 at the lock's Docling, RapidOCR and onnxruntime.
AS_PUBLISHED = "f6578587c74f4bd83cc1505b4004f07dea4e25d42d0e8d53a30d474a51217747"
HALF_PHOTOCOPIED = "7dbfa2fbdbe0a2b953d0a07bdeb9d6555561b95d396dbd625fcfb7a060f64646"

HEADING = "Checkout authorisation success rate, % (2026-07-28, CEST)"


@pytest.fixture(scope="module")
def converter():
    pytest.importorskip("docling", reason="needs dossier[docling]")
    from dossier.infrastructure.converters.docling_markdown import DoclingMarkdownConverter

    return DoclingMarkdownConverter()


class TestDoclingDrawsAPageTheSameOnEveryMachine:
    """R8.28 row 2 — the same artifact wherever it is converted."""

    def test_the_published_postmortem_converts_to_one_artifact(self, converter):
        """Row 2: the one where every page is drawn from fonts it does not embed."""
        artifact = converter.convert(PUBLISHED.read_bytes(), {})

        assert hashlib.sha256(artifact).hexdigest() == AS_PUBLISHED

    def test_the_half_photocopy_keeps_its_heading(self, converter):
        """Row 2: the one where page 1 is read from its text layer beside two pictures.

        On Linux, docling-parse's page 1 folded this heading into the chart
        below it, and the note lost it.
        """
        artifact = converter.convert(photocopy(PUBLISHED.read_bytes(), keep={1}), {})

        assert hashlib.sha256(artifact).hexdigest() == HALF_PHOTOCOPIED
        assert HEADING in artifact.decode("utf-8")
