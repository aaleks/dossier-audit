"""A PNG whose bytes are a function of its pixels (R8.29).

Pillow's PNG encoder is deterministic per build and no further. Its Windows wheel
compresses with zlib-ng and its Linux wheel with zlib, and the same pixels became
different bytes -- different artifacts under one `K_convert` (spec 008, open
question 2). The standard library's `zlib` is no way out: CPython on Windows
links zlib-ng too.

So the image data is compressed by libdeflate, through the `deflate` package
pinned in the `pdf` extra, whose output depends on its input and its level and
on nothing about the machine. The container around it is written here: the
signature, one `IHDR`, one `IDAT` and `IEND`, and nothing else -- no time, no
text, no gamma, nothing a host could fill in differently. Every row is written
with filter type 0: an adaptive filter is a choice an encoder makes, and the
choice is part of the bytes.
"""

from __future__ import annotations

import struct
import zlib
from typing import Any

SIGNATURE = b"\x89PNG\r\n\x1a\n"

# libdeflate's level. Raising it, or the pinned `deflate`, changes every part's
# bytes, and the version of every converter that writes one (R5.4).
LEVEL = 9

# The modes written as they are: greyscale, truecolour and truecolour with
# alpha, eight bits a channel. PNG's colour type for each, and its channels.
_COLOUR_TYPES = {"L": (0, 1), "RGB": (2, 3), "RGBA": (6, 4)}


def png(image: Any) -> bytes:
    """`image`, a Pillow image, as PNG bytes that are the same on every machine.

    A mode PNG is not written in here -- a palette, one bit, CMYK -- is converted
    first, by Pillow's integer arithmetic: to RGBA when it has transparency, and
    to RGB when it has not.
    """
    import deflate

    if image.mode not in _COLOUR_TYPES:
        transparent = "A" in image.mode or "transparency" in image.info
        image = image.convert("RGBA" if transparent else "RGB")

    colour_type, channels = _COLOUR_TYPES[image.mode]
    width, height = image.size
    stride = width * channels
    pixels = image.tobytes()
    rows = b"".join(
        b"\x00" + pixels[row * stride : (row + 1) * stride] for row in range(height)
    )

    header = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
    return (
        SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", deflate.zlib_compress(rows, LEVEL))
        + _chunk(b"IEND", b"")
    )


def _chunk(kind: bytes, body: bytes) -> bytes:
    """One PNG chunk: its length, its type, its data and their CRC-32.

    `zlib.crc32` is a checksum and not a compressor: every implementation of it
    returns the same number, which is what the format defines.
    """
    return (
        struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    )
