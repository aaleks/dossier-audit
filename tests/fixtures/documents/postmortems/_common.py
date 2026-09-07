"""Shared styles, tables and vector graphics for the postmortem fixtures.

Fixture-generation support code, not project code. See generate_postmortems.py.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("SOURCE_DATE_EPOCH", "1755907200")  # 2025-08-23T00:00:00Z

from reportlab import rl_config

rl_config.invariant = 1

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

OUT = Path(__file__).parent / "pdf"

# ---------------------------------------------------------------- palette --

NAVY = colors.HexColor("#1F3864")
STEEL = colors.HexColor("#2E75B6")
INK = colors.HexColor("#222222")
GREY = colors.HexColor("#666666")
RULE = colors.HexColor("#BFBFBF")
LIGHT = colors.HexColor("#F2F2F2")
RED = colors.HexColor("#C00000")
AMBER = colors.HexColor("#ED7D31")
GREEN = colors.HexColor("#2E7D32")
TEAL = colors.HexColor("#0F7B7B")
PANEL_BG = colors.HexColor("#DEEBF7")

SS = getSampleStyleSheet()


def style(name, **kw):
    base = kw.pop("parent", SS["BodyText"])
    return ParagraphStyle(name, parent=base, **kw)


BODY = style("body", fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK,
             spaceAfter=5, alignment=TA_JUSTIFY)
BODY_S = style("bodys", parent=BODY, fontSize=8, leading=11, alignment=0)
MONO = style("mono", fontName="Courier", fontSize=8, leading=11, textColor=INK,
             spaceAfter=4)
MONO_S = style("monos", parent=MONO, fontSize=7, leading=9.5)
H1 = style("h1", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=NAVY,
           spaceAfter=4)
H2 = style("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=NAVY,
           spaceBefore=9, spaceAfter=3)
H2_PLAIN = style("h2p", parent=H2, textColor=INK)
SMALL = style("small", fontName="Helvetica", fontSize=7.5, leading=10, textColor=GREY)
CAPTION = style("caption", parent=SMALL, alignment=TA_CENTER, spaceBefore=2)
SERIF = style("serif", fontName="Times-Roman", fontSize=10, leading=14, textColor=INK,
              spaceAfter=6, alignment=TA_JUSTIFY)
SERIF_H = style("serifh", fontName="Times-Bold", fontSize=11, leading=14, textColor=INK,
                spaceBefore=10, spaceAfter=3)


def P(text, s=BODY):
    return Paragraph(text, s)


def bullets(items, s=BODY, bullet="&bull;"):
    st = ParagraphStyle(f"bul{id(s)}", parent=s, leftIndent=11, spaceAfter=2,
                        alignment=0)
    return [Paragraph(f"{bullet}&nbsp;&nbsp;{i}", st) for i in items]


# ----------------------------------------------------------------- tables --

def kv_table(rows, width, label_w=34 * mm, label_bg=LIGHT, s=BODY_S):
    t = Table([[P(f"<b>{k}</b>", s), P(v, s)] for k, v in rows],
              colWidths=[label_w, width - label_w])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), label_bg),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def grid_table(header, rows, col_widths, head_bg=NAVY, head_fg=colors.white,
               cell_style=BODY_S, zebra=True, grid=RULE):
    th = ParagraphStyle("th", parent=cell_style, textColor=head_fg,
                        fontName="Helvetica-Bold")
    data = [[Paragraph(str(h), th) for h in header]]
    for r in rows:
        data.append([c if hasattr(c, "wrap") else P(str(c), cell_style) for c in r])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), head_bg),
        ("GRID", (0, 0), (-1, -1), 0.4, grid),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if zebra:
        for i in range(2, len(data), 2):
            cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FAFAFA")))
    t.setStyle(TableStyle(cmds))
    return t


def panel(flowables, width, bg=PANEL_BG, bar=STEEL, pad=6):
    inner = Table([[f] for f in flowables], colWidths=[width - 2 * pad - 3])
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    t = Table([["", inner]], colWidths=[3, width - 3])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), bar),
        ("BACKGROUND", (1, 0), (1, -1), bg),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ("LEFTPADDING", (1, 0), (1, -1), pad),
        ("RIGHTPADDING", (1, 0), (1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def tiles(items, width, value_color=NAVY):
    """A row of KPI tiles: [(label, value, sub), ...]."""
    cells = []
    for label, value, sub in items:
        inner = Table([
            [P(label.upper(), ParagraphStyle("tl", parent=SMALL, fontSize=6.5,
                                             textColor=GREY, alignment=TA_CENTER))],
            [P(value, ParagraphStyle("tv", parent=BODY, fontName="Helvetica-Bold",
                                     fontSize=16, leading=19, textColor=value_color,
                                     alignment=TA_CENTER, spaceAfter=0))],
            [P(sub, ParagraphStyle("ts", parent=SMALL, fontSize=6.5,
                                   alignment=TA_CENTER))],
        ])
        inner.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        cells.append(inner)
    n = len(cells)
    gap = 4
    w = (width - gap * (n - 1)) / n
    row, widths = [], []
    for i, c in enumerate(cells):
        if i:
            row.append("")
            widths.append(gap)
        row.append(c)
        widths.append(w)
    t = Table([row], colWidths=widths)
    cmds = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
    for i in range(n):
        col = i * 2
        cmds += [("BOX", (col, 0), (col, 0), 0.5, RULE),
                 ("BACKGROUND", (col, 0), (col, 0), colors.HexColor("#FBFBFD"))]
    t.setStyle(TableStyle(cmds))
    return t


# --------------------------------------------------------------- graphics --

def line_chart(series, labels, width=150 * mm, height=48 * mm, colours=(STEEL,),
               y_min=0, y_max=100, y_step=25, title=None, band=None,
               band_color=colors.HexColor("#FBE5E5")):
    d = Drawing(width, height)
    top = height - (12 if title else 2)
    lc = HorizontalLineChart()
    lc.x = 26
    lc.y = 20
    lc.width = width - 36
    lc.height = top - 22
    lc.data = list(series)
    lc.categoryAxis.categoryNames = labels
    lc.categoryAxis.labels.fontName = "Helvetica"
    lc.categoryAxis.labels.fontSize = 6
    lc.categoryAxis.labels.angle = 0
    lc.categoryAxis.labels.dy = -3
    lc.valueAxis.valueMin = y_min
    lc.valueAxis.valueMax = y_max
    lc.valueAxis.valueStep = y_step
    lc.valueAxis.labels.fontName = "Helvetica"
    lc.valueAxis.labels.fontSize = 6
    lc.joinedLines = 1
    lc.lineLabelFormat = None
    for i, c in enumerate(colours):
        lc.lines[i].strokeColor = c
        lc.lines[i].strokeWidth = 1.4
    if band:
        x0, x1 = band
        n = max(len(labels) - 1, 1)
        px0 = lc.x + lc.width * x0 / n
        px1 = lc.x + lc.width * x1 / n
        d.add(Rect(px0, lc.y, px1 - px0, lc.height, fillColor=band_color,
                   strokeColor=None))
    d.add(lc)
    if title:
        d.add(String(0, height - 9, title, fontName="Helvetica-Bold", fontSize=7.5,
                     fillColor=INK))
    return d


def bar_chart(series, labels, width=150 * mm, height=45 * mm, colours=(STEEL,),
              y_max=None, y_step=None, title=None, series_names=None):
    d = Drawing(width, height)
    top = height - (12 if title else 2)
    bc = VerticalBarChart()
    bc.x = 26
    bc.y = 20
    bc.width = width - 36
    bc.height = top - 22
    bc.data = list(series)
    bc.categoryAxis.categoryNames = labels
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fontSize = 6
    bc.categoryAxis.labels.dy = -3
    bc.valueAxis.valueMin = 0
    if y_max:
        bc.valueAxis.valueMax = y_max
    if y_step:
        bc.valueAxis.valueStep = y_step
    bc.valueAxis.labels.fontName = "Helvetica"
    bc.valueAxis.labels.fontSize = 6
    bc.barSpacing = 1
    bc.groupSpacing = 6
    for i, c in enumerate(colours):
        bc.bars[i].fillColor = c
        bc.bars[i].strokeColor = None
    d.add(bc)
    if title:
        d.add(String(0, height - 9, title, fontName="Helvetica-Bold", fontSize=7.5,
                     fillColor=INK))
    if series_names:
        x = 26
        for i, name in enumerate(series_names):
            c = colours[i % len(colours)]
            d.add(Rect(x, 4, 6, 6, fillColor=c, strokeColor=None))
            d.add(String(x + 9, 5, name, fontName="Helvetica", fontSize=6,
                         fillColor=GREY))
            x += 12 + len(name) * 3.2
    return d


def pie_chart(values, labels, width=80 * mm, height=48 * mm, title=None,
              colours=(STEEL, AMBER, TEAL, RED, colors.HexColor("#8FAADC"))):
    d = Drawing(width, height)
    pie = Pie()
    pie.x = 4
    pie.y = 6
    pie.width = height - 16
    pie.height = height - 16
    pie.data = list(values)
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 0.8
    for i, c in enumerate(colours[:len(values)]):
        pie.slices[i].fillColor = c
    d.add(pie)
    y = height - 18
    for i, lab in enumerate(labels):
        c = colours[i % len(colours)]
        d.add(Rect(pie.width + 14, y, 6, 6, fillColor=c, strokeColor=None))
        d.add(String(pie.width + 23, y + 1, lab, fontName="Helvetica", fontSize=6.5,
                     fillColor=INK))
        y -= 10
    if title:
        d.add(String(0, height - 8, title, fontName="Helvetica-Bold", fontSize=7.5,
                     fillColor=INK))
    return d


def _box(d, x, y, w, h, label, sub=None, fill=colors.white, stroke=STEEL,
         fg=INK, fs=6.5):
    d.add(Rect(x, y, w, h, fillColor=fill, strokeColor=stroke, strokeWidth=0.8))
    ty = y + h / 2 - (1 if sub else 2)
    if sub:
        ty += 4
    d.add(String(x + w / 2, ty, label, fontName="Helvetica-Bold", fontSize=fs,
                 fillColor=fg, textAnchor="middle"))
    if sub:
        d.add(String(x + w / 2, ty - 8, sub, fontName="Helvetica", fontSize=5.5,
                     fillColor=GREY, textAnchor="middle"))


def _arrow(d, x0, y0, x1, y1, colour=GREY, label=None, dashed=False):
    ln = Line(x0, y0, x1, y1, strokeColor=colour, strokeWidth=0.9)
    if dashed:
        ln.strokeDashArray = [2, 2]
    d.add(ln)
    dx, dy = x1 - x0, y1 - y0
    n = max((dx ** 2 + dy ** 2) ** 0.5, 0.001)
    ux, uy = dx / n, dy / n
    px, py = -uy, ux
    d.add(Polygon([x1, y1,
                   x1 - 5 * ux + 2.5 * px, y1 - 5 * uy + 2.5 * py,
                   x1 - 5 * ux - 2.5 * px, y1 - 5 * uy - 2.5 * py],
                  fillColor=colour, strokeColor=colour))
    if label:
        d.add(String((x0 + x1) / 2, (y0 + y1) / 2 + 3, label, fontName="Helvetica",
                     fontSize=5.5, fillColor=GREY, textAnchor="middle"))


def request_path_diagram(width=160 * mm, height=42 * mm, fail_index=2,
                         nodes=(("Client", "browser"), ("CDN edge", "cdn-eu"),
                                ("Resolver", "ns1.internal"), ("Origin LB", "lb-eu-1"),
                                ("Service", "checkout-api"))):
    d = Drawing(width, height)
    d.add(String(0, height - 9, "Request path at time of failure",
                 fontName="Helvetica-Bold", fontSize=7.5, fillColor=INK))
    n = len(nodes)
    gap = 10
    bw = (width - gap * (n - 1)) / n
    bh = 20
    y = height - 40
    xs = []
    for i, (label, sub) in enumerate(nodes):
        x = i * (bw + gap)
        xs.append(x)
        failed = i == fail_index
        _box(d, x, y, bw, bh, label, sub,
             fill=colors.HexColor("#FBE5E5") if failed else colors.white,
             stroke=RED if failed else STEEL, fg=RED if failed else INK)
    for i in range(n - 1):
        _arrow(d, xs[i] + bw, y + bh / 2, xs[i + 1] - 1, y + bh / 2,
               colour=RED if i + 1 == fail_index else GREY)
    fx = xs[fail_index]
    d.add(String(fx + bw / 2, y - 9, "NXDOMAIN — 100% of EU-West lookups",
                 fontName="Helvetica-Bold", fontSize=6, fillColor=RED,
                 textAnchor="middle"))
    return d


def dashboard_screenshot(width=120 * mm, height=42 * mm, title="grafana / auth-svc",
                         panel_titles=("p99 latency (ms)", "5xx rate")):
    """A vector mock of a monitoring screenshot pasted into a report."""
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#20232A"),
               strokeColor=colors.HexColor("#111318")))
    d.add(Rect(0, height - 11, width, 11, fillColor=colors.HexColor("#161922"),
               strokeColor=None))
    d.add(String(5, height - 8, title, fontName="Helvetica", fontSize=6,
                 fillColor=colors.HexColor("#B9C0CC")))
    d.add(String(width - 44, height - 8, "last 6h", fontName="Helvetica", fontSize=5.5,
                 fillColor=colors.HexColor("#7A8291")))
    pw = (width - 15) / 2
    ph = height - 20
    series = [
        [12, 13, 12, 14, 40, 96, 118, 122, 130, 84, 22, 14],
        [0.1, 0.1, 0.2, 0.1, 2.4, 7.8, 9.1, 8.4, 9.6, 3.1, 0.4, 0.1],
    ]
    tints = [colors.HexColor("#73BF69"), colors.HexColor("#F2495C")]
    for i in range(2):
        x = 5 + i * (pw + 5)
        d.add(Rect(x, 5, pw, ph, fillColor=colors.HexColor("#181B20"),
                   strokeColor=colors.HexColor("#2C3038")))
        d.add(String(x + 4, 5 + ph - 8, panel_titles[i], fontName="Helvetica",
                     fontSize=5.5, fillColor=colors.HexColor("#B9C0CC")))
        vals = series[i]
        top = max(vals)
        px, py, pwi, phi = x + 4, 9, pw - 8, ph - 18
        for g in range(1, 4):
            gy = py + phi * g / 4
            d.add(Line(px, gy, px + pwi, gy, strokeColor=colors.HexColor("#2C3038"),
                       strokeWidth=0.4))
        pts = []
        for j, v in enumerate(vals):
            pts += [px + pwi * j / (len(vals) - 1), py + phi * v / top]
        for j in range(0, len(pts) - 2, 2):
            d.add(Line(pts[j], pts[j + 1], pts[j + 2], pts[j + 3],
                       strokeColor=tints[i], strokeWidth=1.1))
    return d


def wave_sparkline(values, width=40 * mm, height=10 * mm, colour=STEEL):
    d = Drawing(width, height)
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pts = []
    for i, v in enumerate(values):
        pts += [width * i / (len(values) - 1), 1 + (height - 2) * (v - lo) / span]
    for i in range(0, len(pts) - 2, 2):
        d.add(Line(pts[i], pts[i + 1], pts[i + 2], pts[i + 3], strokeColor=colour,
                   strokeWidth=1.1))
    return d
