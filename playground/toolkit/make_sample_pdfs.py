#!/usr/bin/env python3
"""Write the playground's sample PDFs and PNG, byte-for-byte reproducibly.

Exercise 03 points at these beside the wiki exports in `corpus/exports/`, and
exercise 04 at the PNG. Two things the repository's own PDF fixtures do not have,
and both are worth practising against:

  * a PDF carrying an embedded image, so `pdf-images` has something to render
    that is not text;
  * a PDF with no text layer at all, so `dossier convert` shows an artifact that
    is a page anchor and nothing else, before a single model call is made -- the
    surprise that command exists for.

Written by hand, with no dependency beyond the standard library, for the reason
the repository's own fixture generator pins `SOURCE_DATE_EPOCH`: a generator that
produced different bytes on a second run would change a snapshot hash for a file
nobody edited. There is no date, no id and no compression level left to chance
here, so running this twice produces identical files.

    python playground/toolkit/make_sample_pdfs.py            # writes playground/corpus/scans/
    python playground/toolkit/make_sample_pdfs.py --out DIR
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

# Two 24x24 RGB images, drawn as a checkerboard from two colours. Small on
# purpose: the point is that bytes came out of a PDF, not what they depict.
TILE = 6
SIZE = 24


def checkerboard(first: tuple[int, int, int], second: tuple[int, int, int]) -> bytes:
    """Raw RGB rows, the form a PDF `/DeviceRGB` image stream holds."""
    rows = []
    for y in range(SIZE):
        for x in range(SIZE):
            rows.append(bytes(first if (x // TILE + y // TILE) % 2 else second))
    return b"".join(rows)


def png(raw_rgb: bytes) -> bytes:
    """The same pixels as a standalone PNG, for the unrecognised-media-type exercise."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    scanlines = b"".join(
        b"\x00" + raw_rgb[y * SIZE * 3 : (y + 1) * SIZE * 3] for y in range(SIZE)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )


def pdf(lines: list[str], image: bytes | None) -> bytes:
    """A one-page PDF holding `lines` of text and, optionally, one embedded image.

    Deliberately minimal and written out object by object: a reader who wants to
    know what a converter is actually handed can read this file top to bottom.
    """
    content = ["BT /F1 11 Tf 56 760 Td 14 TL"]
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content.append(f"({escaped}) Tj T*")
    content.append("ET")
    if image is not None:
        content.append("q 220 0 0 220 56 480 cm /Im1 Do Q")
    stream = "\n".join(content).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources "
            b"<< /Font << /F1 4 0 R >>"
            + (b" /XObject << /Im1 6 0 R >>" if image is not None else b"")
            + b" >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    if image is not None:
        compressed = zlib.compress(image, 9)
        objects.append(
            b"<< /Type /XObject /Subtype /Image /Width "
            + str(SIZE).encode()
            + b" /Height "
            + str(SIZE).encode()
            + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length "
            + str(len(compressed)).encode()
            + b" >>\nstream\n"
            + compressed
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    table = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n"
    ).encode()
    return bytes(out)


# A scan of a paper note: text a converter can extract, and a photograph beside it.
SCAN = [
    "PRODUCTION INCIDENT NOTE  (scanned copy)",
    "Site ..........: Distribution Centre 2",
    "Severity ......: critical",
    "Resolved ......: 2026-04-07",
    "Systems .......: terminal-gateway",
    "Recorded loss .: CHF 61'250",
    "",
    "Photograph of the terminal display, taken by the night shift:",
]

# The same note as a photocopy nobody ran OCR over: an image and no text layer.
NO_TEXT: list[str] = []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "corpus" / "scans",
        help="where to write the files",
    )
    arguments = parser.parse_args(argv)
    arguments.out.mkdir(parents=True, exist_ok=True)

    first = checkerboard((220, 80, 60), (40, 60, 120))
    second = checkerboard((30, 30, 30), (230, 230, 230))

    written = {
        "PLAY-2001-terminal-scan.pdf": pdf(SCAN, first),
        "PLAY-2002-photocopy-no-text-layer.pdf": pdf(NO_TEXT, second),
        "terminal-display.png": png(first),
    }
    for name, payload in written.items():
        path = arguments.out / name
        path.write_bytes(payload)
        print(f"{path} · {len(payload)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
