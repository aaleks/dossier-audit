"""Generate `INC-5720-checkout-latency-postmortem.png` (`specs/_fixtures.md`).

Fixture-generation support code, not project code. Run it only to regenerate
the committed PNG:

    uv run python tests/fixtures/documents/generate_inc_5720.py

The document is a postmortem delivered as one screenshot: prose, a timeline and
a latency chart in a single image, with **no text layer of any kind**. That is
the point of it. `INC-5720` is the standalone-image case for R8.10, and the
figure it carries is the one whose value is stated only in the chart -- the
`loss_amount` axis label is drawn, never written.

Pillow's default bitmap font is used rather than a system TrueType face, so the
bytes do not depend on which fonts a machine happens to have installed (R0.4).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "images" / "INC-5720-checkout-latency-postmortem.png"

WIDTH, HEIGHT = 900, 1160
INK = (28, 32, 38)
MUTED = (104, 112, 124)
RULE = (196, 202, 210)
ACCENT = (178, 42, 52)
PAPER = (252, 252, 250)

PROSE = [
    ("INC-5720  --  Checkout latency degradation", 0, INK),
    ("Postmortem  |  Payments Platform  |  status: closed", 18, MUTED),
    ("", 0, INK),
    ("Summary", 22, INK),
    ("Checkout p99 latency rose from 380 ms to 4.2 s over 94 minutes on", 6, INK),
    ("2026-09-02. Card authorisation timed out for a share of sessions.", 0, INK),
    ("The payments-api pool was exhausted by a retry storm after the", 0, INK),
    ("ledger-batch failover, and no saturation alert existed.", 0, INK),
    ("", 0, INK),
    ("Timeline", 22, INK),
    ("08:14  ledger-batch fails over to the standby host", 6, INK),
    ("08:21  payments-api connection pool saturates", 0, INK),
    ("08:40  first customer report; on-call paged manually", 0, INK),
    ("09:48  pool limits raised, latency recovers", 0, INK),
    ("", 0, INK),
    ("Root cause", 22, INK),
    ("Applications opened unbounded connections during the failover", 6, INK),
    ("and the retry policy amplified every timeout into three more.", 0, INK),
    ("", 0, INK),
    ("Financial impact", 22, INK),
    ("Abandoned checkouts during the window, charted below.", 6, INK),
]

# The chart, and the total drawn beneath it. The total is the only place the
# loss figure appears: no sentence in this document states it, and the prose
# above says only "charted below".
#
# Drawn rather than left to be summed off five bars. A gold answer has to be
# unambiguous -- a reader asked for `loss_amount` from bars alone could
# defensibly answer the peak (61'300) or the total, and a gold value with two
# defensible readings measures the reader rather than the system (R7.7).
BARS = [
    ("08:00", 2_400),
    ("08:30", 18_100),
    ("09:00", 61_300),
    ("09:30", 44_200),
    ("10:00", 6_400),
]
AXIS = ["CHF 0", "CHF 18k", "CHF 36k", "CHF 54k", "CHF 72k"]
CEILING = 72_000
TOTAL = "Total abandoned checkout value over the window:  CHF 132'400"


def _chart(draw: ImageDraw.ImageDraw, top: int) -> None:
    left, width, height = 190, 520, 210
    base = top + height

    for index, label in enumerate(AXIS):
        y = base - round(index * height / (len(AXIS) - 1))
        draw.line([(left, y), (left + width, y)], fill=RULE)
        draw.text((left - 78, y - 6), label, fill=MUTED)

    slot = width // len(BARS)
    for index, (label, value) in enumerate(BARS):
        bar = round(value / CEILING * height)
        x = left + index * slot + slot // 4
        draw.rectangle([(x, base - bar), (x + slot // 2, base)], fill=ACCENT)
        draw.text((x, base + 10), label, fill=MUTED)

    draw.line([(left, top), (left, base)], fill=INK)
    draw.line([(left, base), (left + width, base)], fill=INK)
    draw.text((left - 78, top - 26), "Abandoned checkout value", fill=INK)
    # The figure a gold answer names, drawn into the picture. Nothing in the
    # prose above repeats it, so a stage that reads only the text layer cannot
    # reach it at all -- which is the whole reason this fixture exists.
    draw.text((left - 78, base + 46), TOTAL, fill=INK)


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)

    y = 56
    for text, gap, colour in PROSE:
        y += gap
        if text:
            draw.text((60, y), text, fill=colour)
        y += 20

    _chart(draw, y + 60)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # `optimize` and no ancillary chunks: nothing here carries a timestamp, so
    # the committed bytes are reproducible on any machine (R0.4).
    image.save(OUT, format="PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
