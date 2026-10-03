"""What a masked document reads as (spec 021).

A masker finds candidate spans: that is the one thing it is trusted with, and
it decides nothing. Which spans are masked, how overlapping ones resolve, and
what each one becomes are decisions, made here, where they are provable with
plain values and no masker at all -- and where mutation testing can reach them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    """A span a masker found: where it is, what it says it is, and how sure it is."""

    start: int
    end: int
    entity: str
    score: float


def merged(detections: Sequence[Detection]) -> list[Detection]:
    """Overlapping detections as one span covering them all, in text order (R21.3).

    Presidio finds `example.ch` as a URL inside an e-mail address, and a person
    inside a company's name. Masked one by one, they would leave a piece of the
    value standing between two placeholders, so a run of overlapping spans
    becomes one, and covers every one of them: masking more is the safe side.
    The span takes the type of its longest detection; a tie is broken by the
    type first by name, which never varies, rather than by the order a masker
    happened to list them in.
    """
    groups: list[list[Detection]] = []
    for detection in sorted(detections, key=lambda d: (d.start, d.end)):
        if groups and detection.start < max(d.end for d in groups[-1]):
            groups[-1].append(detection)
        else:
            groups.append([detection])
    spans = []
    for group in groups:
        winner = min(group, key=lambda d: (-(d.end - d.start), d.entity))
        spans.append(
            Detection(
                start=min(d.start for d in group),
                end=max(d.end for d in group),
                entity=winner.entity,
                score=winner.score,
            )
        )
    return spans


def masked(text: str, detections: Sequence[Detection]) -> str:
    """`text` with each detected value replaced by `[TYPE_n]` (R21.2).

    Numbered per type by first appearance, so a model shown the masked text can
    still tell two people apart and follow one through a document.
    """
    numbers: dict[tuple[str, str], int] = {}
    counts: dict[str, int] = {}
    pieces: list[str] = []
    at = 0
    for detection in sorted(detections, key=lambda d: d.start):
        value = (detection.entity, _same(text[detection.start : detection.end]))
        if value not in numbers:
            counts[detection.entity] = counts.get(detection.entity, 0) + 1
            numbers[value] = counts[detection.entity]
        pieces.append(text[at : detection.start])
        pieces.append(f"[{detection.entity}_{numbers[value]}]")
        at = detection.end
    pieces.append(text[at:])
    return "".join(pieces)


def _same(value: str) -> str:
    """The form two mentions of one value share: a heading in capitals, or a
    name wrapped across a line, is not a second client (R21.2 row 2)."""
    return " ".join(value.split()).casefold()
