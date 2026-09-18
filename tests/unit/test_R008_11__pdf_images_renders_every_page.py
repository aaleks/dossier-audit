"""R8.11 — a page-images conversion is one container of one PNG per page.

The container format itself is proved in
`test_R008_11__a_multi_part_conversion_is_one_container.py`. This file is the
rows that need the binary fixtures: a real three-page postmortem and a photocopy
with no text layer.

`application/pdf` is a named exemption from R8.1's conformance rows, so the
purity claims for this converter are made here as they are for `pdf-markdown`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pypdfium2", reason="pdf-images needs the 'pdf' extra")

from dossier.domain.conversion import unpack_parts
from dossier.infrastructure.converters.pdf_images import PdfImagesConverter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
CORPUS = FIXTURES / "postmortems" / "pdf"
SCANS = FIXTURES / "scans"

COMPLETE = "INC-4830-postmortem-checkout-tls-expiry.pdf"
NO_TEXT_LAYER = "PLAY-2002-photocopy-no-text-layer.pdf"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def converter() -> PdfImagesConverter:
    return PdfImagesConverter()


class TestEveryPageIsRendered:
    """R8.11 — one artifact, one PNG per page, in page order."""

    def test_a_three_page_postmortem_yields_three_pictures(self, converter: PdfImagesConverter):
        """Example 1: the one where a document becomes its pages."""
        parts = unpack_parts(converter.convert((CORPUS / COMPLETE).read_bytes(), {}))

        assert len(parts) == 3
        assert all(part.startswith(PNG_MAGIC) for part in parts)

    def test_a_photocopy_renders_exactly_as_any_other_page_does(
        self, converter: PdfImagesConverter
    ):
        """Example 3: the one this kind exists for.

        `pdf-markdown` converts this document to its anchors and nothing else,
        because there is no text layer to read. Rendering does not care: the
        picture is all there ever was, and this is the only way to reach it.
        """
        parts = unpack_parts(converter.convert((SCANS / NO_TEXT_LAYER).read_bytes(), {}))

        assert len(parts) == 1
        assert parts[0].startswith(PNG_MAGIC)
        assert len(parts[0]) > 1000, "a rendered page is a real picture"

    def test_converting_twice_produces_identical_bytes(self, converter: PdfImagesConverter):
        """Example 2: the one where nothing about the second call differs (R8.1)."""
        payload = (CORPUS / COMPLETE).read_bytes()

        assert converter.convert(payload, {}) == converter.convert(payload, {})

    def test_it_claims_the_pair_the_default_kind_sends_an_image_to(
        self, converter: PdfImagesConverter
    ):
        """The one that connects this converter to R8.10.

        A PDF asks for `page_images` only when its source says so; a PNG asks
        for it by default. The kind is the same either way, which is what makes
        one describe step able to read both.
        """
        assert (converter.media_type, converter.kind) == ("application/pdf", "page_images")

    def test_bytes_that_are_not_a_pdf_fail_against_their_own_document(
        self, converter: PdfImagesConverter
    ):
        """Counter-example: the one where the payload was never a PDF.

        `ValueError` is R8.6's shape -- one document fails with a reason and the
        others convert -- and deliberately not R8.5's, which would stop the run.
        """
        with pytest.raises(ValueError, match="pdf-images"):
            converter.convert(b"not a pdf at all", {})
