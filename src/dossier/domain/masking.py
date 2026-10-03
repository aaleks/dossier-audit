"""What a masked document reads as (spec 021).

A masker finds candidate spans: that is the one thing it is trusted with, and
it decides nothing. Which spans are masked, how overlapping ones resolve, and
what each one becomes are decisions, made here, where they are provable with
plain values and no masker at all -- and where mutation testing can reach them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from dossier.domain.hashing import content_hash

# The version of these rules: the numbering, the overlaps and the filter. It is
# in every masked view's key (R21.5), and moves whenever they could write a
# different text for the same input -- a converter's version promises the same
# of its artifacts (R5.4). A masked view cached by the old rules and served by
# the new would claim to be something they no longer produce.
MASKING_VERSION = "1"


# The kind of a converted artifact that is pictures, not text. A masked pipeline
# refuses any step reading it: a client's name in the pixels of a page cannot be
# masked by anything here (R21.7).
PICTURES = "page_images"


class MaskerUnavailable(RuntimeError):
    """The masker cannot mask at all on this machine: a model it reads with is missing.

    Not one document's failure (R21.8) but the masker's, so it stops the run
    before any model is asked, naming what installs it (R21.7, R21.10). It is
    never caught as a document's failure: every document would fail alike.
    """


class MaskPattern(BaseModel):
    """A recogniser of the pipeline's own, such as the bank's client number."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regex: str
    score: float = Field(ge=0.0, le=1.0)
    context: list[str] = []


class MaskingDeclaration(BaseModel):
    """`masking/cid.yaml`: what a pipeline masks, and with what (spec 021).

    `score_threshold` has no default. Presidio scores each recogniser with a
    constant, so the threshold decides which recognisers count, and that is
    the pipeline author's decision rather than a number `dossier` ships.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    masker: str
    languages: list[str] = Field(min_length=1)
    score_threshold: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(min_length=1)
    patterns: dict[str, MaskPattern] = {}
    allow: str | None = None


@dataclass(frozen=True)
class Masking:
    """A pipeline's masking as loaded: its declaration, the hash of every file
    the declaration is made of (R21.5), and the values its allow-list names."""

    declaration: MaskingDeclaration
    declaration_hash: str
    allow: tuple[str, ...] = ()


def unmaskable_steps(steps: Sequence[tuple[str, Sequence[str]]]) -> list[str]:
    """The steps, by id, that read a kind nothing can mask (R21.7 row 1).

    Each step is its id and the inputs it declares, as `pipeline.yaml` writes
    them: `documents@page_images` reads pictures, and a picture of a page
    holds the client's name where no masker reaches it.
    """
    return [
        step
        for step, inputs in steps
        if any(name.rpartition("@")[2] == PICTURES for name in inputs if "@" in name)
    ]


def unrecognised(declaration: MaskingDeclaration, recognised: Collection[str]) -> list[str]:
    """The declared types nothing would find, in declaration order (R21.7 row 4).

    A type no recogniser and no declared pattern provides is a type the author
    believes is masked and is not: it is refused, never silently passed over.
    """
    found = set(recognised) | set(declaration.patterns)
    return [entity for entity in declaration.entities if entity not in found]


@dataclass(frozen=True)
class Detection:
    """A span a masker found: where it is, what it says it is, and how sure it is."""

    start: int
    end: int
    entity: str
    score: float


def declaration_hash(files: Mapping[str, bytes]) -> str:
    """One hash for a masking declaration and every file it names (R21.5).

    `cid.yaml` alone would leave its allow-list out: a vendor added to
    `allow.txt` changes what is masked and would change no key. Each file is
    hashed under its name, in name order, so the same files give the same hash
    on any machine (R0.4).
    """
    named = {name: content_hash(data) for name, data in sorted(files.items())}
    return content_hash(
        json.dumps(named, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def kept(
    text: str,
    detections: Sequence[Detection],
    *,
    entities: Collection[str],
    threshold: float,
    allow: Collection[str],
) -> list[Detection]:
    """The detections that are masked: declared, at the threshold or above, not allowed (R21.4).

    A detection *at* the threshold is masked. Presidio scores each recogniser
    with a constant, so the threshold is a choice of which recognisers count,
    and one equal to a recogniser's score is a choice to count it. An
    allow-listed value -- a vendor, a system, a site -- is never masked,
    whatever its score; it is compared as two mentions of a value are (R21.2).
    """
    allowed = {_same(value) for value in allow}
    return [
        detection
        for detection in detections
        if detection.entity in entities
        and detection.score >= threshold
        and _same(text[detection.start : detection.end]) not in allowed
    ]


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
    return _numbered(text, detections, {})[0]


def _numbered(
    text: str, detections: Sequence[Detection], mapping: Mapping[str, str]
) -> tuple[str, dict[str, str]]:
    """`text` masked, numbering on from `mapping`; and the mapping it ends with.

    `mapping` is a document's, placeholder to the value it stands for: a value
    it holds keeps its placeholder, and a new one takes the next number of its
    type (R21.22). Empty, numbering starts at one (R21.2). The mapping returned
    holds each value as it was first written.
    """
    numbers: dict[tuple[str, str], int] = {}
    counts: dict[str, int] = {}
    held = dict(mapping)
    for placeholder, value in mapping.items():
        found = _PLACEHOLDER.fullmatch(placeholder)
        if found is None:
            continue
        entity, number = found.group(1), int(found.group(2))
        numbers[(entity, _same(value))] = number
        counts[entity] = max(counts.get(entity, 0), number)
    pieces: list[str] = []
    at = 0
    for detection in sorted(detections, key=lambda d: d.start):
        written = text[detection.start : detection.end]
        value = (detection.entity, _same(written))
        if value not in numbers:
            counts[detection.entity] = counts.get(detection.entity, 0) + 1
            numbers[value] = counts[detection.entity]
        placeholder = f"[{detection.entity}_{numbers[value]}]"
        held.setdefault(placeholder, written)
        pieces.append(text[at : detection.start])
        pieces.append(placeholder)
        at = detection.end
    pieces.append(text[at:])
    return "".join(pieces), held


# A placeholder as `masked` writes it: the type, which may hold underscores,
# and its number.
_PLACEHOLDER = re.compile(r"\[([A-Z][A-Z_]*)_(\d+)\]")


def mapping_values(text: str, mapping: Mapping[str, str]) -> list[Detection]:
    """Each place `text` writes a value of `mapping`, as a detection of its type (R21.22).

    Found by the value itself, compared as two mentions are (R21.2): a gold
    value or a candidate need not be found by a masker to be the document's
    value, and a masker may miss a name in a short sentence it found in the
    document.
    """
    found: list[Detection] = []
    for placeholder, value in mapping.items():
        typed = _PLACEHOLDER.fullmatch(placeholder)
        words = value.split()
        if typed is None or not words:
            continue
        pattern = re.compile(r"\s+".join(re.escape(word) for word in words), re.IGNORECASE)
        found.extend(
            Detection(start=hit.start(), end=hit.end(), entity=typed.group(1), score=1.0)
            for hit in pattern.finditer(text)
        )
    return found


def _same(value: str) -> str:
    """The form two mentions of one value share: a heading in capitals, or a
    name wrapped across a line, is not a second client (R21.2 row 2)."""
    return " ".join(value.split()).casefold()


def mask(
    text: str, detections: Sequence[Detection], masking: Masking
) -> tuple[str, dict[str, int]]:
    """A document as a masked pipeline shows it, and how many values of each type it masked.

    The one composition of the three decisions: which detections count
    (R21.4), overlaps as one span (R21.3), and the placeholders (R21.2). The
    counts are for the provenance record and MLflow, never the values.
    """
    masked_text, _, counts = mask_with_mapping(text, detections, masking)
    return masked_text, counts


def mask_with_mapping(
    text: str, detections: Sequence[Detection], masking: Masking
) -> tuple[str, dict[str, str], dict[str, int]]:
    """`mask`, and the document's mapping from placeholder to value beside it (R21.21).

    The mapping is what a gold value or a calibration candidate is masked
    with, so that the same client has the same placeholder in the document and
    in what a person wrote about it (R21.22). It is kept on this machine only.
    """
    spans = merged(_kept(text, detections, masking))
    masked_text, mapping = _numbered(text, spans, {})
    return masked_text, mapping, _counts(spans)


def mask_like(
    text: str, detections: Sequence[Detection], masking: Masking, mapping: Mapping[str, str]
) -> str:
    """`text` masked with a document's numbering (R21.22).

    A value of the document -- found by itself, or by the masker -- takes the
    document's placeholder; anything else the masker finds takes the next
    number of its type. A text that holds neither is returned as written.
    """
    spans = merged([*_kept(text, detections, masking), *mapping_values(text, mapping)])
    return _numbered(text, spans, mapping)[0]


def _kept(text: str, detections: Sequence[Detection], masking: Masking) -> list[Detection]:
    declared = masking.declaration
    return kept(
        text,
        detections,
        entities=declared.entities,
        threshold=declared.score_threshold,
        allow=masking.allow,
    )


def _counts(spans: Sequence[Detection]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for span in spans:
        counts[span.entity] = counts.get(span.entity, 0) + 1
    return dict(sorted(counts.items()))


# The words of each language that carry no meaning of their own: articles,
# conjunctions, prepositions, the commonest verbs. Every document has many of
# them, and no client is called one. Lower case; a document's words are folded
# before they are counted. Part of the masking rules: a change to a list can
# choose another language for a document, so it raises MASKING_VERSION.
FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        [
            "the",
            "and",
            "of",
            "to",
            "in",
            "is",
            "was",
            "that",
            "for",
            "it",
            "with",
            "on",
            "as",
            "by",
            "at",
            "from",
            "this",
            "were",
            "be",
            "not",
            "an",
            "are",
            "has",
            "had",
            "have",
            "which",
            "after",
        ]
    ),
    "de": frozenset(
        [
            "der",
            "die",
            "das",
            "und",
            "ist",
            "nicht",
            "mit",
            "den",
            "ein",
            "eine",
            "zu",
            "von",
            "auf",
            "für",
            "im",
            "dem",
            "sich",
            "war",
            "wurde",
            "des",
            "bei",
            "nach",
            "auch",
            "einer",
            "wurden",
            "aus",
        ]
    ),
    "fr": frozenset(
        [
            "le",
            "la",
            "les",
            "et",
            "est",
            "des",
            "une",
            "un",
            "du",
            "en",
            "que",
            "pour",
            "dans",
            "pas",
            "sur",
            "au",
            "avec",
            "par",
            "été",
            "qui",
            "aux",
            "ont",
            "il",
            "elle",
            "sont",
        ]
    ),
    "it": frozenset(
        [
            "il",
            "la",
            "di",
            "che",
            "e",
            "è",
            "per",
            "non",
            "una",
            "un",
            "del",
            "della",
            "con",
            "sono",
            "gli",
            "nel",
            "da",
            "al",
            "stato",
            "alle",
            "dei",
            "delle",
            "anche",
            "era",
        ]
    ),
}
_WORD = re.compile(r"[^\W\d_]+")


def language_of(text: str, languages: Sequence[str]) -> str:
    """The declared language whose function words `text` uses most (R21.9).

    One language per document, because a named-entity model reading the wrong
    language finds names that are not names and misses the ones that are.
    Counted only among the declared languages: one the author did not declare
    is never chosen. A tie, or a text with no votes at all -- a CSV of numbers
    -- falls to the order the author declared them in, which never varies.
    """
    words = [word.casefold() for word in _WORD.findall(text)]
    votes = {
        language: sum(word in FUNCTION_WORDS.get(language, frozenset()) for word in words)
        for language in languages
    }
    return max(languages, key=lambda language: (votes[language], -languages.index(language)))


# What separates the words of a file name or a key. A named-entity model reads
# `Erika-Mustermann-complaint.pdf` as one word and finds no person in it; read
# with these as spaces it finds her (measured 2026-10-03, R21.8 row 2).
_KEY_SEPARATORS = str.maketrans({separator: " " for separator in "-_./+"})


def readable_key(key: str) -> str:
    """`key` as a masker should read it: its separators as spaces, every offset kept.

    A key is shown to the model in every `<document key="...">` (R3.13), so a
    file named after a client carries the name past its masked text unless
    the key itself is checked -- and a key's words are joined by hyphens,
    underscores and dots, which a model trained on prose does not split on.
    """
    return key.translate(_KEY_SEPARATORS)
