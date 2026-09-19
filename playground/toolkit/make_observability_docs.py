#!/usr/bin/env python3
"""Write the playground's observability documents: five PDFs and one PNG.

    python playground/toolkit/make_observability_docs.py             # -> corpus/observability/
    python playground/toolkit/make_observability_docs.py --out DIR
    python playground/toolkit/make_observability_docs.py --digests   # each page's sha256

These are the documents exercise 10 runs over, and every one of them carries a
picture a text layer cannot express: an APM latency chart, a Grafana JVM memory
panel, a Kibana error screenshot, a throughput chart. `corpus/scans/` already has
a PDF with *an* image in it; what it does not have is a document whose evidence
is only readable by looking -- which is the whole subject of `page_images`, of a
`per_part` step, and of the `described` grounding state (R8.11, R3.12, R6.15).

Each PDF carries a real text layer *and* a panel, and that pairing is deliberate:

  * the severity, the date, the systems and the root cause are written in the
    text, so a field citing them is **grounded** -- a string search finds the span;
  * the money figure is drawn on the panel and written in no sentence anywhere,
    so a field citing it is **described** -- there is no text to search, and a
    judge shown the pages decides it (R6.15, R7.21).

`PLAY-3006` is the counter-case: a screenshot with no text layer at all, where
every field is described because there is nothing to search.

Reproducibility, which is the reason this is a script and not a folder of files
somebody exported: Pillow's bundled font is used rather than a system face, no
timestamp is written into any PNG, the PDF objects are emitted in a fixed order
with no date and no id, and every compression level is stated. Running this twice
produces byte-identical files -- otherwise a snapshot hash would change for a
document nobody edited (R0.4, R0.2).

Pillow is needed here, as it is for `dossier[pdf]`. `pypdfium2` is needed only
for `--digests`, which renders the pages the way a run will.
"""

from __future__ import annotations

import argparse
import hashlib
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PANEL = (760, 400)

# Light, for the tools that are light, and dark for the one that is. Two
# palettes rather than one because a Grafana panel a reader recognises is worth
# more here than a house style: the point of these documents is that they look
# like the things people actually paste into a postmortem.
PAPER = (255, 255, 255)
INK = (26, 28, 33)
MUTED = (105, 112, 125)
GRID = (226, 232, 240)
EDGE = (203, 213, 225)

DARK_PAPER = (24, 27, 31)
DARK_INK = (216, 217, 218)
DARK_MUTED = (138, 145, 154)
DARK_GRID = (44, 50, 53)

BLUE = (0, 119, 204)
AMBER = (245, 167, 0)
RED = (189, 39, 30)
GREEN = (115, 191, 105)
YELLOW = (250, 222, 42)
VIOLET = (135, 106, 210)


def font(size: int) -> ImageFont.FreeTypeFont:
    """Pillow's bundled face at `size`.

    Bundled rather than a system font on purpose: `DejaVuSans` is present on one
    machine and absent on the next, and a document whose bytes depend on which
    fonts a laptop happens to carry is a snapshot hash that changes for no
    reason anybody can see (R0.4).
    """
    return ImageFont.load_default(size=size)


@dataclass(frozen=True)
class Series:
    """One plotted line: its label, its colour, and its points."""

    label: str
    colour: tuple[int, int, int]
    values: Sequence[float]


def _axes(
    draw: ImageDraw.ImageDraw,
    *,
    box: tuple[int, int, int, int],
    ceiling: float,
    ticks: Sequence[str],
    columns: Sequence[str],
    grid: tuple[int, int, int],
    muted: tuple[int, int, int],
) -> None:
    """The gridlines, the y ticks and the x labels of one panel."""
    left, top, right, bottom = box
    small = font(13)
    for index, label in enumerate(ticks):
        y = bottom - round(index * (bottom - top) / (len(ticks) - 1))
        draw.line([(left, y), (right, y)], fill=grid)
        draw.text((left - 54, y - 7), label, font=small, fill=muted, anchor="la")
    step = (right - left) / max(len(columns) - 1, 1)
    for index, label in enumerate(columns):
        x = left + round(index * step)
        draw.text((x, bottom + 10), label, font=small, fill=muted, anchor="ma")


def _plot(
    draw: ImageDraw.ImageDraw,
    *,
    box: tuple[int, int, int, int],
    ceiling: float,
    series: Sequence[Series],
    width: int = 2,
) -> None:
    """Each series as a polyline inside `box`."""
    left, top, right, bottom = box
    for line in series:
        step = (right - left) / max(len(line.values) - 1, 1)
        points = [
            (left + index * step, bottom - (value / ceiling) * (bottom - top))
            for index, value in enumerate(line.values)
        ]
        draw.line(points, fill=line.colour, width=width, joint="curve")


def _legend(
    draw: ImageDraw.ImageDraw,
    *,
    at: tuple[int, int],
    series: Sequence[Series],
    ink: tuple[int, int, int],
) -> None:
    x, y = at
    small = font(13)
    for line in series:
        draw.rectangle([(x, y + 4), (x + 16, y + 8)], fill=line.colour)
        draw.text((x + 24, y), line.label, font=small, fill=ink, anchor="la")
        x += 34 + round(draw.textlength(line.label, font=small))


def _figure(
    draw: ImageDraw.ImageDraw,
    *,
    at: tuple[int, int],
    text: str,
    ink: tuple[int, int, int],
    accent: tuple[int, int, int],
) -> None:
    """The money figure, drawn into the picture and written in no sentence.

    This is the line that makes each of these documents worth having. A stage
    that reads only the text layer cannot reach it at all, so a field citing it
    is `described` rather than grounded, and the judge that decides it has to be
    shown the pages (R6.15, R7.21).
    """
    x, y = at
    draw.rectangle([(x, y), (x + 4, y + 20)], fill=accent)
    draw.text((x + 14, y + 2), text, font=font(16), fill=ink, anchor="la")


def apm_latency(*, title: str, subtitle: str, figure: str) -> Image.Image:
    """An APM transaction-latency panel: three percentiles over the window."""
    image = Image.new("RGB", PANEL, PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle([(0, 0), (PANEL[0] - 1, PANEL[1] - 1)], outline=EDGE)

    draw.text((24, 18), title, font=font(18), fill=INK, anchor="la")
    draw.text((24, 44), subtitle, font=font(13), fill=MUTED, anchor="la")

    series = [
        Series("p50", BLUE, [120, 124, 130, 180, 240, 310, 380, 420, 360, 240, 180, 150, 140]),
        Series(
            "p95",
            AMBER,
            [310, 320, 360, 700, 1200, 1900, 2600, 2900, 2500, 1400, 760, 520, 430],
        ),
        Series(
            "p99", RED, [380, 400, 520, 1400, 2600, 3600, 4200, 4100, 3400, 2100, 980, 620, 470]
        ),
    ]
    box = (86, 92, 736, 296)
    _axes(
        draw,
        box=box,
        ceiling=4500,
        ticks=["0", "1.1 s", "2.3 s", "3.4 s", "4.5 s"],
        columns=["08:00", "08:30", "09:00", "09:30", "10:00"],
        grid=GRID,
        muted=MUTED,
    )
    _plot(draw, box=box, ceiling=4500, series=series)
    draw.line([(box[0], box[1]), (box[0], box[3]), (box[2], box[3])], fill=EDGE)
    _legend(draw, at=(86, 334), series=series, ink=MUTED)
    _figure(draw, at=(86, 358), text=figure, ink=INK, accent=RED)
    return image


def grafana_jvm(*, title: str, subtitle: str, figure: str) -> Image.Image:
    """A Grafana JVM memory panel: heap used against heap max, and GC pauses."""
    image = Image.new("RGB", PANEL, DARK_PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle([(0, 0), (PANEL[0] - 1, PANEL[1] - 1)], outline=DARK_GRID)

    draw.text((24, 18), title, font=font(18), fill=DARK_INK, anchor="la")
    draw.text((24, 44), subtitle, font=font(13), fill=DARK_MUTED, anchor="la")

    # A sawtooth whose troughs climb: every collection reclaims less than the
    # one before it, which is what a leak looks like on this panel and what the
    # root cause sentence in the text layer says in words.
    used = [1.2, 2.4, 3.1, 1.4, 2.6, 3.4, 1.9, 3.0, 3.6, 2.4, 3.4, 3.8, 3.9]
    series = [
        Series("heap used", GREEN, used),
        Series("heap max", YELLOW, [4.0] * len(used)),
        Series(
            "GC pause (s)",
            VIOLET,
            [0.1, 0.1, 0.2, 0.2, 0.3, 0.4, 0.6, 0.8, 1.1, 1.3, 1.6, 1.8, 1.9],
        ),
    ]
    box = (86, 92, 736, 296)
    _axes(
        draw,
        box=box,
        ceiling=4.5,
        ticks=["0", "1.1 GB", "2.3 GB", "3.4 GB", "4.5 GB"],
        columns=["08:00", "08:30", "09:00", "09:30", "10:00"],
        grid=DARK_GRID,
        muted=DARK_MUTED,
    )
    _plot(draw, box=box, ceiling=4.5, series=series)
    draw.line([(box[0], box[1]), (box[0], box[3]), (box[2], box[3])], fill=DARK_GRID)
    _legend(draw, at=(86, 334), series=series, ink=DARK_MUTED)
    _figure(draw, at=(86, 358), text=figure, ink=DARK_INK, accent=GREEN)
    return image


KIBANA_ROWS = [
    ("08:21:04.812", "ERROR", "edge-gateway  502 Bad Gateway  upstream=checkout-api  30001ms"),
    ("08:21:04.960", "ERROR", "checkout-api  PoolExhaustedException: no connection after 30s"),
    ("08:22:17.331", "WARN ", "edge-gateway  canary weight 25% -> retry budget exhausted"),
    ("08:24:02.107", "ERROR", "checkout-api  PoolExhaustedException: no connection after 30s"),
]


def kibana_errors(*, title: str, subtitle: str, hits: str, figure: str) -> Image.Image:
    """A Kibana Discover screenshot: the hit histogram and the first log rows."""
    image = Image.new("RGB", PANEL, PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle([(0, 0), (PANEL[0] - 1, PANEL[1] - 1)], outline=EDGE)
    draw.rectangle([(1, 1), (PANEL[0] - 2, 38)], fill=(242, 246, 252))

    draw.text((24, 11), title, font=font(16), fill=INK, anchor="la")
    draw.text((PANEL[0] - 24, 13), hits, font=font(14), fill=BLUE, anchor="ra")
    draw.text((24, 50), subtitle, font=font(13), fill=MUTED, anchor="la")

    counts = [4, 9, 31, 210, 640, 980, 1240, 1180, 870, 410, 120, 38, 12]
    box = (86, 78, 736, 188)
    _axes(
        draw,
        box=box,
        ceiling=1400,
        ticks=["0", "700", "1,400"],
        columns=["08:00", "08:30", "09:00", "09:30", "10:00"],
        grid=GRID,
        muted=MUTED,
    )
    slot = (box[2] - box[0]) / len(counts)
    for index, count in enumerate(counts):
        height = round(count / 1400 * (box[3] - box[1]))
        x = box[0] + index * slot
        draw.rectangle([(x + 3, box[3] - height), (x + slot - 3, box[3])], fill=(38, 100, 178))
    draw.line([(box[0], box[1]), (box[0], box[3]), (box[2], box[3])], fill=EDGE)

    mono = font(13)
    y = 216
    draw.text((28, y), "Time", font=mono, fill=MUTED, anchor="la")
    draw.text((140, y), "level", font=mono, fill=MUTED, anchor="la")
    draw.text((208, y), "message", font=mono, fill=MUTED, anchor="la")
    y += 18
    for stamp, level, message in KIBANA_ROWS:
        draw.line([(24, y - 4), (736, y - 4)], fill=GRID)
        draw.text((28, y), stamp, font=mono, fill=INK, anchor="la")
        draw.text(
            (140, y), level.strip(), font=mono, fill=RED if level.strip() == "ERROR" else AMBER
        )
        draw.text((208, y), message, font=mono, fill=INK, anchor="la")
        y += 22

    _figure(draw, at=(24, 358), text=figure, ink=INK, accent=RED)
    return image


def throughput(*, title: str, subtitle: str, figure: str) -> Image.Image:
    """A plain chart: requests per second, with the error rate over it."""
    image = Image.new("RGB", PANEL, PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle([(0, 0), (PANEL[0] - 1, PANEL[1] - 1)], outline=EDGE)

    draw.text((24, 18), title, font=font(18), fill=INK, anchor="la")
    draw.text((24, 44), subtitle, font=font(13), fill=MUTED, anchor="la")

    rps = [1180, 1210, 1160, 940, 610, 380, 240, 310, 520, 880, 1120, 1190, 1200]
    box = (86, 92, 736, 296)
    _axes(
        draw,
        box=box,
        ceiling=1400,
        ticks=["0", "350", "700", "1,050", "1,400"],
        columns=["22:00", "22:30", "23:00", "23:30", "00:00"],
        grid=GRID,
        muted=MUTED,
    )
    slot = (box[2] - box[0]) / len(rps)
    for index, value in enumerate(rps):
        height = round(value / 1400 * (box[3] - box[1]))
        x = box[0] + index * slot
        draw.rectangle([(x + 4, box[3] - height), (x + slot - 4, box[3])], fill=(148, 178, 214))
    series = [
        Series(
            "error rate %",
            RED,
            [0.2, 0.2, 0.4, 2.1, 6.4, 11.8, 18.2, 14.6, 8.1, 3.2, 0.9, 0.3, 0.2],
        )
    ]
    _plot(draw, box=box, ceiling=20, series=series)
    draw.line([(box[0], box[1]), (box[0], box[3]), (box[2], box[3])], fill=EDGE)
    _legend(
        draw,
        at=(86, 334),
        series=[Series("requests/s", (148, 178, 214), []), *series],
        ink=MUTED,
    )
    _figure(draw, at=(86, 358), text=figure, ink=INK, accent=RED)
    return image


# --------------------------------------------------------------------------
# The PDF container: text layer plus one panel per page.
# --------------------------------------------------------------------------


def _escape(line: str) -> str:
    return line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


TOP = 782
LEADING = 15
PANEL_WIDTH, PANEL_HEIGHT = 483, 254


def _page_stream(lines: Sequence[str], *, has_image: bool) -> bytes:
    """One page's content: the text layer, then the panel it carries."""
    content = [f"BT /F1 11 Tf 56 {TOP} Td {LEADING} TL"]
    for line in lines:
        content.append(f"({_escape(line)}) Tj T*")
    content.append("ET")
    if has_image:
        # Under the last line, rather than at a fixed height. A page with five
        # lines of text would otherwise leave a hand's width of nothing between
        # the prose and the panel, and half of what a vision model is shown
        # would be blank paper.
        #
        # 483 x 254 keeps the panel's 760 x 400 aspect ratio, so nothing a
        # reader is asked to read off it is squashed.
        bottom = TOP - LEADING * len(lines) - 28 - PANEL_HEIGHT
        content.append(f"q {PANEL_WIDTH} 0 0 {PANEL_HEIGHT} 56 {max(bottom, 56)} cm /Im1 Do Q")
    return "\n".join(content).encode("latin-1")


def pdf(pages: Sequence[tuple[Sequence[str], Image.Image | None]]) -> bytes:
    """A PDF of `pages`, each one text and at most one picture.

    Written out object by object with no library, and no date, id or producer
    string anywhere: a reader who wants to know what a converter is handed can
    read this function top to bottom, and two runs produce the same bytes.
    """
    # 1 catalog, 2 pages, 3 font: fixed numbers, so a page written below can
    # refer to its parent and its font before either object exists.
    objects: list[bytes] = [
        b"",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids: list[int] = []

    for lines, panel in pages:
        stream = _page_stream(lines, has_image=panel is not None)
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
        content_number = len(objects)

        image_number = None
        if panel is not None:
            raw = panel.tobytes()
            compressed = zlib.compress(raw, 9)
            objects.append(
                b"<< /Type /XObject /Subtype /Image /Width "
                + str(panel.width).encode()
                + b" /Height "
                + str(panel.height).encode()
                + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length "
                + str(len(compressed)).encode()
                + b" >>\nstream\n"
                + compressed
                + b"\nendstream"
            )
            image_number = len(objects)

        resources = b"<< /Font << /F1 3 0 R >>"
        if image_number is not None:
            resources += b" /XObject << /Im1 " + str(image_number).encode() + b" 0 R >>"
        resources += b" >>"
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources "
            + resources
            + b" /Contents "
            + str(content_number).encode()
            + b" 0 R >>"
        )
        kids.append(len(objects))

    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{number} 0 R".encode() for number in kids)
        + b"] /Count "
        + str(len(kids)).encode()
        + b" >>"
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
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


# --------------------------------------------------------------------------
# The documents.
# --------------------------------------------------------------------------


def _header(key: str, page: int, of: int, title: str) -> list[str]:
    """The two lines every page carries, and the reason they are there.

    A `per_part` step's prompt holds the document's text and nothing that says
    *which page* the picture is -- the page reaches the model as an image, not as
    a substitution. So the page says it itself, in the text layer and therefore
    in the rendering: a model asked to cite `source.document` has somewhere to
    read the key from, and a person looking at part three of four does too.
    """
    return [title, f"Document key: {key}   |   page {page} of {of}", ""]


@dataclass(frozen=True)
class Document:
    """One playground document: its key, its pages, and what it is for."""

    key: str
    title: str
    pages: Sequence[tuple[Sequence[str], Callable[[], Image.Image] | None]] = field(
        default_factory=tuple
    )


SUMMARY_3001 = [
    "Severity: critical",
    "Resolved: 2026-09-02",
    "Affected systems: checkout-service, payments-gateway",
    "",
    "Root cause: the canary released at 08:04 halved the checkout-service",
    "connection pool while leaving the retry budget unchanged, so every timed-out",
    "request was retried three times against a pool that was already full.",
    "",
    "Revenue at risk is shown on the panel below. It is stated in no sentence of",
    "this note, deliberately: read it off the chart.",
]

SUMMARY_3002 = [
    "Severity: major",
    "Resolved: 2026-09-03",
    "Affected systems: payments-api",
    "",
    "Root cause: entries written to the retry cache during the ledger-batch",
    "failover were never evicted, so the old generation grew until every",
    "collection reclaimed less than the one before it.",
    "",
    "Revenue at risk is shown on the panel below and is written nowhere in this",
    "note.",
]

SUMMARY_3003 = [
    "Severity: critical",
    "Resolved: 2026-09-04",
    "Affected systems: edge-gateway, checkout-api",
    "",
    "Root cause: the 25% canary on edge-gateway routed to a build whose upstream",
    "timeout was 30 seconds against a client timeout of 10, so every slow",
    "checkout call was counted twice and returned 502.",
    "",
    "Revenue at risk is shown on the screenshot below and is written nowhere in",
    "this note.",
]

SUMMARY_3004 = [
    "Severity: minor",
    "Resolved: 2026-09-05",
    "Affected systems: ledger-batch",
    "",
    "Root cause: the nightly reconciliation kept the clock it was given before",
    "the daylight-saving change, so it started an hour into the online window and",
    "competed with live traffic for the same database.",
    "",
    "Revenue at risk is shown on the chart below and is written nowhere in this",
    "note.",
]

SUMMARY_3005 = [
    "Severity: critical",
    "Resolved: 2026-09-08",
    "Affected systems: checkout-service, payments-api, edge-gateway",
    "",
    "Root cause: the three incidents of the week share one cause -- a retry",
    "budget that is configured per service and enforced nowhere, so each",
    "component amplified the failure of the one beneath it.",
    "",
    "The three panels that follow are the evidence the review was held over. The",
    "revenue at risk for the week is on the last of them and in no sentence here.",
]

DOCUMENTS = [
    Document(
        key="PLAY-3001-checkout-latency-apm.pdf",
        title="PLAY-3001  --  Checkout latency degradation",
        pages=[
            (
                _header(
                    "PLAY-3001-checkout-latency-apm.pdf",
                    1,
                    1,
                    "PLAY-3001  --  Checkout latency degradation",
                )
                + SUMMARY_3001,
                lambda: apm_latency(
                    title="APM  ·  checkout-service  ·  transaction latency",
                    subtitle="2026-09-02  08:00-10:00 UTC  ·  environment: production",
                    figure="Revenue at risk over the window:  CHF 84'600",
                ),
            )
        ],
    ),
    Document(
        key="PLAY-3002-jvm-heap-grafana.pdf",
        title="PLAY-3002  --  Payments API heap exhaustion",
        pages=[
            (
                _header(
                    "PLAY-3002-jvm-heap-grafana.pdf",
                    1,
                    1,
                    "PLAY-3002  --  Payments API heap exhaustion",
                )
                + SUMMARY_3002,
                lambda: grafana_jvm(
                    title="JVM Memory  --  payments-api",
                    subtitle="2026-09-03  08:00-10:00 UTC  ·  datasource: prometheus-prod",
                    figure="Revenue at risk over the window:  CHF 27'900",
                ),
            )
        ],
    ),
    Document(
        key="PLAY-3003-kibana-error-spike.pdf",
        title="PLAY-3003  --  Edge gateway 502 spike",
        pages=[
            (
                _header(
                    "PLAY-3003-kibana-error-spike.pdf",
                    1,
                    1,
                    "PLAY-3003  --  Edge gateway 502 spike",
                )
                + SUMMARY_3003,
                lambda: kibana_errors(
                    title="Discover  ·  logs-payments-*",
                    subtitle=(
                        "2026-09-04  08:00-10:00 UTC  ·  "
                        "query: level:ERROR AND service:edge-gateway"
                    ),
                    hits="12,481 hits",
                    figure="Revenue at risk over the window:  CHF 41'250",
                ),
            )
        ],
    ),
    Document(
        key="PLAY-3004-batch-overlap-throughput.pdf",
        title="PLAY-3004  --  Ledger batch overlap",
        pages=[
            (
                _header(
                    "PLAY-3004-batch-overlap-throughput.pdf",
                    1,
                    1,
                    "PLAY-3004  --  Ledger batch overlap",
                )
                + SUMMARY_3004,
                lambda: throughput(
                    title="Checkout throughput and error rate",
                    subtitle="2026-09-05  22:00-00:00 UTC  ·  source: edge-gateway access log",
                    figure="Revenue at risk over the window:  CHF 6'400",
                ),
            )
        ],
    ),
    Document(
        key="PLAY-3005-weekly-incident-review.pdf",
        title="PLAY-3005  --  Weekly incident review",
        pages=[
            (
                _header(
                    "PLAY-3005-weekly-incident-review.pdf",
                    1,
                    4,
                    "PLAY-3005  --  Weekly incident review",
                )
                + SUMMARY_3005,
                None,
            ),
            (
                _header(
                    "PLAY-3005-weekly-incident-review.pdf",
                    2,
                    4,
                    "PLAY-3005  --  Weekly incident review  --  latency",
                )
                + ["Checkout latency across the week, by percentile."],
                lambda: apm_latency(
                    title="APM  ·  checkout-service  ·  transaction latency",
                    subtitle="week of 2026-09-01  ·  environment: production",
                    figure="Peak p99 for the week:  4.2 s at 09:04 on 2026-09-02",
                ),
            ),
            (
                _header(
                    "PLAY-3005-weekly-incident-review.pdf",
                    3,
                    4,
                    "PLAY-3005  --  Weekly incident review  --  memory",
                )
                + ["Heap behaviour on payments-api during the same week."],
                lambda: grafana_jvm(
                    title="JVM Memory  --  payments-api",
                    subtitle="week of 2026-09-01  ·  datasource: prometheus-prod",
                    figure="Heap used never returned below:  2.4 GB after 09:00",
                ),
            ),
            (
                _header(
                    "PLAY-3005-weekly-incident-review.pdf",
                    4,
                    4,
                    "PLAY-3005  --  Weekly incident review  --  errors",
                )
                + ["Errors logged across the week, and the cost of them."],
                lambda: kibana_errors(
                    title="Discover  ·  logs-payments-*",
                    subtitle="week of 2026-09-01  ·  query: level:ERROR",
                    hits="31,904 hits",
                    figure="Revenue at risk over the window:  CHF 118'750",
                ),
            ),
        ],
    ),
]


def error_budget_screenshot() -> Image.Image:
    """`PLAY-3006`: a screenshot, and therefore a document with no text at all.

    Everything a reader needs is drawn -- the key, the severity, the date, the
    systems, the root cause and the figure. Nothing is in a text layer, because
    there is no text layer: a PNG has one kind, `page_images`, and that is the
    whole of what R8.10's table resolves it to. Every field extracted from this
    document is `described` for exactly that reason (R6.15, R8.12).
    """
    width, height = 900, 1180
    image = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(image)

    draw.text((56, 48), "PLAY-3006  ·  Error budget review", font=font(24), fill=INK)
    draw.text(
        (56, 84),
        "Document key: PLAY-3006-error-budget-screenshot.png   ·   page 1 of 1",
        font=font(14),
        fill=MUTED,
    )
    draw.text(
        (56, 106),
        "Screenshot pasted into the review. No text layer of any kind.",
        font=font(14),
        fill=MUTED,
    )
    draw.line([(56, 136), (844, 136)], fill=EDGE)

    lines = [
        ("Severity: major", 16, INK),
        ("Resolved: 2026-09-11", 16, INK),
        ("Affected systems: checkout-service, edge-gateway", 16, INK),
        ("", 16, INK),
        ("Root cause: the error budget for checkout-service was consumed in four", 16, INK),
        ("days by retries that were never counted against it, because the budget is", 16, INK),
        ("measured at the edge and the retries are issued behind it.", 16, INK),
    ]
    y = 158
    for text, size, colour in lines:
        if text:
            draw.text((56, y), text, font=font(size), fill=colour)
        y += 24

    panel = apm_latency(
        title="Error budget burn  ·  checkout-service",
        subtitle="2026-09-07 - 2026-09-11  ·  target: 99.9% availability",
        figure="Revenue at risk over the window:  CHF 53'100",
    )
    image.paste(panel, (70, y + 16))

    screenshot = kibana_errors(
        title="Discover  ·  logs-checkout-*",
        subtitle="2026-09-11  ·  query: level:ERROR AND retry:true",
        hits="8,204 hits",
        figure="Retries not counted against the budget:  81% of all errors",
    )
    image.paste(screenshot, (70, y + 16 + PANEL[1] + 24))
    return image


PNG_KEY = "PLAY-3006-error-budget-screenshot.png"


def write(out: Path) -> dict[str, bytes]:
    """Every document, as the bytes that go on disk."""
    written: dict[str, bytes] = {}
    for document in DOCUMENTS:
        written[document.key] = pdf(
            [(lines, None if panel is None else panel()) for lines, panel in document.pages]
        )

    buffer = out / PNG_KEY
    # `optimize=True` and nothing ancillary: Pillow writes no timestamp into a
    # PNG, so the committed bytes are the same on every machine (R0.4).
    error_budget_screenshot().save(buffer, format="PNG", optimize=True)
    written[PNG_KEY] = buffer.read_bytes()
    return written


def digests(out: Path) -> list[tuple[str, str, str]]:
    """Each document's pages as a run will see them: key, part, sha256.

    Rendered by the **shipped** converters rather than by anything written here,
    because the only bytes worth printing are the ones a step is actually handed
    (R8.11, R8.12). That is what makes the numbers usable in a stub reply file:
    the picture is the only thing that differs between two calls of a `per_part`
    step, so it is the only thing a stub can tell them apart by -- which is the
    same fact as the part being in the cache key (R3.12).
    """
    from dossier.domain.conversion import unpack_parts
    from dossier.infrastructure.converters.image_pages import PngPagesConverter
    from dossier.infrastructure.converters.pdf_images import PdfImagesConverter

    rows: list[tuple[str, str, str]] = []
    for key in sorted(p.name for p in out.iterdir() if p.is_file()):
        payload = (out / key).read_bytes()
        converter = PngPagesConverter() if key.endswith(".png") else PdfImagesConverter()
        for position, part in enumerate(unpack_parts(converter.convert(payload, {})), start=1):
            rows.append((key, f"page-{position:03d}.png", hashlib.sha256(part).hexdigest()))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "corpus" / "observability",
        help="where to write the documents",
    )
    parser.add_argument(
        "--digests",
        action="store_true",
        help="print each page's sha256 as the shipped converters render it",
    )
    arguments = parser.parse_args(argv)
    arguments.out.mkdir(parents=True, exist_ok=True)

    for name, payload in write(arguments.out).items():
        path = arguments.out / name
        path.write_bytes(payload)
        print(f"{path} · {len(payload)} bytes")

    if arguments.digests:
        print()
        for key, part, digest in digests(arguments.out):
            print(f"{digest[:16]}  {key}  {part}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
