"""What `dossier search` decides (spec 019).

A search asks the index twice -- by meaning and by words -- and everything
after the asking is decided here: how the two ranked lists become one, how a
document is ranked by its chunks, what text the query is embedded as, and what
a filter or a reader may name. Pure, so the order a search prints is provable
without a database.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from dossier.domain.grounding import enum_folded

# The constant of reciprocal rank fusion: a chunk's score is the sum, over the
# lists it is in, of 1 / (RRF_K + rank). 60 is Cormack et al.'s (2009), and the
# one pgvector's hybrid-search guidance uses; agreed by `a.aleks` on 2026-10-01.
RRF_K = 60
# How many chunks each list holds, after the filters. OPEN: whether 100 is
# enough for ten documents on a real corpus is spec 019's open question 1.
CANDIDATES = 100
# What a query is embedded after when an index declares no instruction (spec
# 019, "The query instruction").
DEFAULT_INSTRUCTION = (
    "Given a question about incidents, retrieve the passages of incident records "
    "and documents that answer it"
)


@dataclass(frozen=True)
class Candidate:
    """A chunk, as one of a search's two lists returned it (R19.1)."""

    chunk_id: str
    document_id: str
    # `body` or `record` (spec 018).
    kind: str
    heading_path: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Described:
    """A document a search found, as the index holds it: its title and carried values."""

    document_id: str
    title: str
    values: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Lists:
    """What the index answered a search: two ranked lists of chunks, and their documents.

    `meaning` is nearest first, by cosine distance to the query's vector;
    `words` is best first, by `ts_rank_cd` over the chunks the query's words
    match. Each holds at most the candidates asked for, after the filters.
    `documents` describes every document a chunk in either list belongs to.
    """

    meaning: tuple[Candidate, ...] = ()
    words: tuple[Candidate, ...] = ()
    documents: Mapping[str, Described] = field(default_factory=dict)


@dataclass(frozen=True)
class Ranked:
    """A chunk in a search's fused order: its score, and its rank in each list (R19.1)."""

    candidate: Candidate
    score: float
    # Its place in each list, counted from 1, or `None` for a list it is not in.
    meaning: int | None = None
    words: int | None = None


def fused(
    *, meaning: Sequence[Candidate], words: Sequence[Candidate], k: int = RRF_K
) -> tuple[Ranked, ...]:
    """The chunks of both lists, best first, by reciprocal rank fusion (R19.1).

    A chunk is scored by where it stands in each list, not by its distance or
    its text rank, which are on scales that cannot be added: `1 / (k + rank)`
    for each list it is in. A chunk found only by words still ranks -- an
    incident key is found by words and is near nothing in meaning. Equal scores
    are ordered by chunk id, so the order is the same on every machine.
    """
    places: dict[str, dict[str, int]] = {}
    chunks: dict[str, Candidate] = {}
    for name, ranked in (("meaning", meaning), ("words", words)):
        for rank, candidate in enumerate(ranked, start=1):
            chunks.setdefault(candidate.chunk_id, candidate)
            places.setdefault(candidate.chunk_id, {}).setdefault(name, rank)
    scored = [
        Ranked(
            candidate=chunks[chunk_id],
            # Meaning first, then words, so the same sum is the same float.
            score=sum(1 / (k + place[name]) for name in ("meaning", "words") if name in place),
            meaning=place.get("meaning"),
            words=place.get("words"),
        )
        for chunk_id, place in places.items()
    ]
    return tuple(sorted(scored, key=lambda ranked: (-ranked.score, ranked.candidate.chunk_id)))


def listed(ranked: Sequence[Ranked], *, limit: int, chunks: bool = False) -> tuple[Ranked, ...]:
    """What a search lists: documents, each once at its best chunk, or the chunks (R19.2).

    A person looks for incidents, not fragments, and one long runbook must not
    fill the page; `chunks` lists the fused chunks as they are, cut at `limit`.
    """
    if chunks:
        return tuple(ranked[:limit])
    best: dict[str, Ranked] = {}
    for each in ranked:
        best.setdefault(each.candidate.document_id, each)
        if len(best) == limit:
            break
    return tuple(best.values())


def query_text(query: str, *, instruction: str | None) -> str:
    """The text a query is embedded as: after its instruction, in Qwen3's format (R19.3).

    `None` is the default instruction; an instruction declared empty embeds
    the query as typed, for a model trained without one. Documents are
    embedded without one (spec 018).
    """
    told = DEFAULT_INSTRUCTION if instruction is None else instruction
    if not told:
        return query
    return f"Instruct: {told}\nQuery:{query}"


class UnfilterableWhere(ValueError):
    """A `--where` the index cannot answer: no `=`, a field it does not filter on, or a value
    the field does not declare (R19.4). Refused before the model is asked."""


def wheres(
    given: Sequence[str],
    *,
    index: str,
    filters: Sequence[str],
    enums: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Each `FIELD=VALUE` given, as the values each field may hold (R19.4).

    Two fields must both hold; one field given twice may hold either value. A
    value is read in the spelling its declaration writes, found by the fold
    the scorer compares by, so a filter finds what `embed` carried (R18.9 row
    5). Raises `UnfilterableWhere` for anything the index cannot answer: a
    typo would otherwise find nothing, and look like an answer.
    """
    chosen: dict[str, tuple[str, ...]] = {}
    for pair in given:
        name, equals, value = pair.partition("=")
        name, value = name.strip(), value.strip()
        if not equals or not name or not value:
            raise UnfilterableWhere(f"--where takes FIELD=VALUE; got {pair}")
        if name not in filters:
            listed_filters = ", ".join(sorted(filters))
            raise UnfilterableWhere(
                f"{name} is not a filter of {index}; its filters are {listed_filters}"
            )
        declared = (enums or {}).get(name)
        if declared is not None:
            spelled = {enum_folded(each): each for each in declared}
            if enum_folded(value) not in spelled:
                values = ", ".join(sorted(declared))
                raise UnfilterableWhere(
                    f"{value} is not a value of {name}; it declares {values}"
                )
            value = spelled[enum_folded(value)]
        if value not in chosen.get(name, ()):
            chosen[name] = (*chosen.get(name, ()), value)
    return chosen


class ReadersRefused(ValueError):
    """`--as` and `--all-readers` that name no search: neither, both, or a reader no
    source declares (R19.10, R19.11). Refused before the model is asked."""


def readers_for(
    named: Sequence[str], *, all_readers: bool, declared: Collection[str], pipeline: str
) -> tuple[str, ...] | None:
    """The readers a search is for, each once and in order, or `None` for every chunk.

    The connection reads every row, so the application holding it keeps readers
    apart: a search names the readers it is for, or asks for every chunk, and
    one that does neither is refused rather than listing every chunk for an
    agent that forgot `--as` (R19.11). A reader no source of the pipeline
    declares would narrow the search silently, and is refused (R19.10).
    """
    known = ", ".join(sorted(declared))
    if named and all_readers:
        raise ReadersRefused(
            "--as and --all-readers contradict: name the readers, or ask for every chunk"
        )
    if all_readers:
        return None
    if not named:
        raise ReadersRefused(
            f"name the readers this search is for with --as READER ({known}), "
            "or search every chunk with --all-readers"
        )
    for reader in named:
        if reader not in declared:
            raise ReadersRefused(
                f"no source of {pipeline} declares {reader} as a reader; they declare {known}"
            )
    return tuple(sorted(set(named)))


def header(index: str, *, found: int, readers: Sequence[str] | None, chunks: bool) -> str:
    """The line a search opens with: what was found, and for whom (R19.10 - R19.12)."""
    unit = "chunk" if chunks else "document"
    counted = f"{found} {unit}{'' if found == 1 else 's'}"
    who = "not filtered by reader" if readers is None else f"as {', '.join(readers)}"
    return f"{index} · {counted} · {who}"


def model_refusal(index: str, *, held: Collection[str], declared: str) -> str | None:
    """Why a search of `index` is refused before the model is asked, or `None` (R19.6).

    A query vector from one model is meaningless against another's, and the
    lengths need not even agree.
    """
    if not held:
        return f"{index} holds nothing yet: run dossier embed {index}"
    if set(held) != {declared}:
        return (
            f"{index} was embedded with {', '.join(sorted(held))}, and is declared with "
            f"{declared}: run dossier embed {index}"
        )
    return None


def unreflected(*, held: Mapping[str, str], indexed: Mapping[str, str]) -> int:
    """How many documents the index does not hold as the ledger holds them (R19.7).

    `held` and `indexed` map a document id to its snapshot. A document synced
    since the last embed, changed since, or tombstoned since each count once.
    """
    return sum(
        1
        for document in held.keys() | indexed.keys()
        if held.get(document) != indexed.get(document)
    )


def unreflected_line(index: str, count: int) -> str | None:
    """The line saying so, or `None` when the index reflects every held document (R19.7)."""
    if count == 0:
        return None
    documents = "document" if count == 1 else "documents"
    return f"{count} held {documents} not in {index} as held: run dossier embed {index}"


# How long a result's text is shown, at most, on its one line (R19.12 row 1).
EXCERPT = 200


def excerpt(text: str, *, limit: int = EXCERPT) -> str:
    """A chunk's text on one line, cut at a word to at most `limit` characters (R19.12).

    Cut with `…`, so a reader knows there is more; a word longer than the
    whole limit is cut where the limit falls.
    """
    line = " ".join(text.split())
    if len(line) <= limit:
        return line
    cut = line[:limit].rsplit(" ", 1)[0] if " " in line[:limit] else line[:limit]
    return f"{cut.rstrip()}…"


def values_line(values: Mapping[str, object]) -> str | None:
    """A document's carried values, by field name, or `None` when it carries none (R19.12)."""
    if not values:
        return None
    shown = (
        f"{name}: {', '.join(map(str, value)) if isinstance(value, list | tuple) else value}"
        for name, value in sorted(values.items())
    )
    return " · ".join(shown)
