"""R8.29 — a PNG a converter writes is compressed by one pinned deflate, so its
bytes are a function of its pixels.

Pillow's PNG encoder is deterministic per build and no further: its Windows
wheel compresses with zlib-ng, its Linux wheel with zlib, and the same pixels
became different bytes (spec 008, open question 2). The pinned hashes below are
the proof that crosses machines. This suite runs on Windows where it is
written, and on Linux in CI; a hash that holds on one and not the other is
exactly the failure this rule exists to stop.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image", reason="the picture converters need Pillow")
pytest.importorskip("deflate", reason="R8.29's encoder is libdeflate: needs dossier[pdf]")

from dossier.domain.conversion import unpack_parts  # noqa: E402
from dossier.infrastructure.converters._png import png  # noqa: E402
from dossier.infrastructure.converters.image_pages import (  # noqa: E402
    JpegPagesConverter,
    PngPagesConverter,
)

CHART = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "documents"
    / "images"
    / "INC-5720-checkout-latency-postmortem.png"
)

# Written on Windows 11 (Pillow built with zlib-ng) and held by CI on Linux
# (Pillow built with zlib). Raising `deflate`, or the level, moves these, and a
# converter's version with them (R5.4).
CHART_PNG = "31439acbc3a8f7e8513bc0d19ef1591fdbfd62dcb6fce083b4715fe82b15b211"
JPEG_PART = "f6aa00e16de601e7ddc7d14d5c41d7a0f023fcccb96c581e0ab46fd87459bffa"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gradient_jpeg() -> bytes:
    """A JPEG whose pixels are arithmetic, so its bytes are the same everywhere."""
    image = Image.new("RGB", (64, 32))
    image.putdata([(x * 4, y * 8, (x + y) * 2) for y in range(32) for x in range(64)])
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class TestAPngIsAFunctionOfItsPixels:
    """R8.29 — the same pixels, the same bytes, on every machine."""

    def test_the_charts_pixels_encode_to_one_set_of_bytes(self):
        """Row 1: the one where the machine does not choose the compressor.

        Decoded from a committed PNG, so the pixels are the same on both
        machines, and encoded here. The hash is the same on Windows and Linux,
        where Pillow's own `save` gave two.
        """
        with Image.open(CHART) as chart:
            chart.load()
            assert sha(png(chart)) == CHART_PNG

    def test_a_jpeg_is_re_encoded_the_same_way(self):
        """Row 2: the one where `jpeg-pages` writes its part with it."""
        (part,) = unpack_parts(JpegPagesConverter().convert(gradient_jpeg(), {}))

        assert sha(part) == JPEG_PART

    @pytest.mark.parametrize("mode", ["L", "RGB", "RGBA"])
    def test_a_part_reads_back_as_the_pixels_it_was_given(self, mode: str):
        """Row 3: the one where any reader, and any provider, decodes it.

        Same size, same mode and the same pixels. A PNG only `dossier` could
        read would be no use as a part a model is sent.
        """
        with Image.open(CHART) as chart:
            image = chart.convert(mode)

        with Image.open(io.BytesIO(png(image))) as decoded:
            assert decoded.size == image.size
            assert decoded.mode == mode
            assert decoded.tobytes() == image.tobytes()

    def test_a_palette_image_is_written_as_its_colours(self):
        """The one where a mode PNG has no single answer for is made one first."""
        with Image.open(CHART) as chart:
            image = chart.convert("P")

        with Image.open(io.BytesIO(png(image))) as decoded:
            assert decoded.mode == "RGB"
            assert decoded.tobytes() == image.convert("RGB").tobytes()

    def test_a_png_source_is_copied_not_re_encoded(self):
        """Counter-example (row 4): the one whose bytes are the input's already."""
        payload = CHART.read_bytes()

        (part,) = unpack_parts(PngPagesConverter().convert(payload, {}))

        assert part == payload
