"""R8.12 — an image converts to `page_images` as a container of one part.

R8.10 resolved `image/png` to `page_images` and nothing produced that pair, so
its row 4 fired for every image: the default decided which pair had to be
claimed, and no converter claimed it.

The container is the part worth a test of its own. One page's bytes would have
been simpler and would have made a picture the one `page_images` artifact a
`per_part` step could not fan out over (R8.11, R3.12).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from dossier.domain.conversion import unpack_parts
from dossier.infrastructure.converters.image_pages import (
    JpegPagesConverter,
    PngPagesConverter,
)

IMAGES = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "images"
CHART = IMAGES / "INC-5720-checkout-latency-postmortem.png"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def jpeg() -> bytes:
    """A small JPEG, built here rather than committed.

    Generated because the repository holds no JPEG and one exists only to prove
    the re-encode: committing a binary fixture for a single assertion would be a
    file nobody could review.
    """
    pillow = pytest.importorskip("PIL.Image", reason="the picture converters need Pillow")
    buffer = io.BytesIO()
    pillow.new("RGB", (8, 4), color=(200, 40, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


class TestAnImageConvertsToOnePageImage:
    """R8.12 — one image, one part, always a PNG."""

    def test_a_png_is_one_part_copied_byte_for_byte(self):
        """Example 1: the one that makes `image/png` a pair something claims.

        Byte-for-byte is the assertion, not "is a PNG". A converter that
        decoded and re-encoded would still produce a PNG, and would make the
        artifact depend on a Pillow version its own `version` does not name.
        """
        payload = CHART.read_bytes()

        parts = unpack_parts(PngPagesConverter().convert(payload, {}))

        assert len(parts) == 1
        assert parts[0] == payload

    def test_a_jpeg_becomes_a_png(self, jpeg: bytes):
        """Example 2: the one where the part's type is the type it is sent as.

        The parts carry no media type of their own -- the composition root
        labels each one `image/png` as it unpacks a container -- so a JPEG
        passed through verbatim would reach a provider under a type it is not.
        """
        parts = unpack_parts(JpegPagesConverter().convert(jpeg, {}))

        assert len(parts) == 1
        assert parts[0].startswith(PNG_MAGIC), "a part is a PNG whatever the source was"
        assert parts[0] != jpeg

    def test_converting_twice_gives_the_same_bytes(self, jpeg: bytes):
        """Example 3: the one R5.6 needs.

        Two conversions of one input on one machine, which is the half of
        determinism a test can check. The other half -- two machines -- is what
        keeping Pillow on its documented defaults is for.
        """
        converter = JpegPagesConverter()

        assert converter.convert(jpeg, {}) == converter.convert(jpeg, {})

    def test_a_truncated_image_fails_with_a_reason(self, jpeg: bytes):
        """Counter-example 5: the one where a bad input is not a bad pipeline.

        R8.6 wants this document to fail and the others to convert, which needs
        a `ValueError` carrying something a person can act on -- not a Pillow
        exception escaping from three frames down.
        """
        with pytest.raises(ValueError, match="could not read this image"):
            JpegPagesConverter().convert(jpeg[: len(jpeg) // 3], {})

    def test_each_converter_claims_exactly_one_pair(self):
        """R8.3's shape, held for the pair of them.

        Two converters rather than one with two media types. Sharing an identity
        would make `jpeg-pages` and `png-pages` bump their versions together,
        and only one of them has a re-encoder underneath to bump for (R5.4).
        """
        png, jpg = PngPagesConverter(), JpegPagesConverter()

        assert (png.media_type, png.kind) == ("image/png", "page_images")
        assert (jpg.media_type, jpg.kind) == ("image/jpeg", "page_images")
        assert png.id != jpg.id
