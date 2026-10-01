"""What `dossier search` decides (spec 019).

A search asks the index twice -- by meaning and by words -- and everything
after the asking is decided here: how the two ranked lists become one, how a
document is ranked by its chunks, what text the query is embedded as, and what
a filter or a reader may name. Pure, so the order a search prints is provable
without a database.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

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
