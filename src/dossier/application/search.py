"""`dossier search`: the documents an index holds that answer a query (spec 019).

The index and the embedding model are handed in, as a run's model client is;
this module constructs neither. The model is asked only for the query's
vector, and only when the cache has none (R19.3). What the index answers is
ranked by `dossier.domain.search`, and reaches the terminal and MLflow and
nothing else: no key, manifest or score (R0.19).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dossier.application.embed import cached_vector, keep_vector
from dossier.domain.index import IndexDeclaration
from dossier.domain.ports import ArtifactStore, EmbeddingProvider, IndexSearch, Tracker
from dossier.domain.search import (
    CANDIDATES,
    Described,
    Ranked,
    fused,
    listed,
    model_refusal,
    query_text,
    unreflected,
)
from dossier.domain.tracking import label_for, run_name
from dossier.domain.tracking import tags as tracking_tags


class SearchRefused(ValueError):
    """A search that cannot be answered as asked, before the model is asked (R19.6)."""


@dataclass(frozen=True)
class Found:
    """One result: its place, its chunk as ranked, and its document."""

    rank: int
    ranked: Ranked
    document: Described


@dataclass(frozen=True)
class SearchReport:
    """What a search found, and what it cost."""

    index: str
    query: str
    # The readers it was for, or `None` for every chunk (R19.10, R19.11).
    readers: tuple[str, ...] | None
    chunks: bool
    found: tuple[Found, ...]
    # Held documents the index does not hold as held (R19.7).
    unreflected: int
    model: str
    # The text the query was embedded as, and whether its vector was cached.
    embedded_as: str
    cached: bool
    tokens: int | None = None


def search_index(
    *,
    declaration: IndexDeclaration,
    query: str,
    where: Mapping[str, Sequence[str]],
    readers: tuple[str, ...] | None,
    limit: int,
    chunks: bool,
    embedder: EmbeddingProvider,
    vectors: ArtifactStore,
    index: IndexSearch,
    held: Mapping[str, str],
    candidates: int = CANDIDATES,
    words: str | None = None,
) -> SearchReport:
    """Search `declaration`'s index for `query` (spec 019).

    The index is asked which model it was embedded with before the model is
    asked anything: a query vector from another model is meaningless against
    it (R19.6). `held` is each document the ledger holds now, by id, with its
    snapshot, to say how many the index does not reflect (R19.7).

    `candidates` and `words` are a measurement's to change (R22.9, R22.10): a
    search asks each list for 100 chunks, by the query's words as written.
    """
    model = declaration.embedding_model
    refusal = model_refusal(
        declaration.name, held=index.models(declaration.name), declared=model
    )
    if refusal is not None:
        raise SearchRefused(refusal)
    text = query_text(query, instruction=declaration.query_instruction)
    vector = cached_vector(vectors, model, text)
    cached, tokens = vector is not None, None
    if vector is None:
        (reply,) = embedder.embed([text])
        vector = tuple(reply)
        tokens = getattr(embedder, "last_tokens", None)
        keep_vector(vectors, model, text, vector)
    lists = index.search(
        declaration.name,
        vector=vector,
        # Words are the query's own: the instruction is for the model.
        words=query if words is None else words,
        where=where,
        readers=readers,
        candidates=candidates,
    )
    shown = listed(fused(meaning=lists.meaning, words=lists.words), limit=limit, chunks=chunks)
    return SearchReport(
        index=declaration.name,
        query=query,
        readers=readers,
        chunks=chunks,
        found=tuple(
            Found(
                rank=rank, ranked=ranked, document=lists.documents[ranked.candidate.document_id]
            )
            for rank, ranked in enumerate(shown, start=1)
        ),
        unreflected=unreflected(held=held, indexed=index.snapshots(declaration.name)),
        model=model,
        embedded_as=text,
        cached=cached,
        tokens=tokens,
    )


def record_search(
    tracker: Tracker,
    *,
    experiment: str,
    report: SearchReport,
    where: Mapping[str, Sequence[str]],
    pipeline: str,
    environ: Mapping[str, str],
    label: str = "",
) -> None:
    """Record a search as one trace in `experiment`, under no run (R11.35).

    A search changes nothing, so it opens no run, as a `--plan` records
    nothing. Its trace is what MLflow's retrieval views read: the query and
    its filters as the request, the documents in rank order as the response,
    an EMBEDDING span for the query's vector and a RETRIEVER span for what the
    index answered.
    """
    label = label_for(label, environ)
    tracker.use_experiment(experiment)
    search_trace(
        tracker, report=report, where=where, pipeline=pipeline, environ=environ, label=label
    )
    tracker.end_traces()


def search_trace(
    tracker: Tracker,
    *,
    report: SearchReport,
    where: Mapping[str, Sequence[str]],
    pipeline: str,
    environ: Mapping[str, str],
    label: str,
) -> None:
    """One search as one trace: the query as its request, an EMBEDDING and a RETRIEVER span.

    In whatever the tracker is recording: under no run for a search (R11.35),
    under the measurement's run for each query a measurement searches (R11.37).
    Choosing the experiment is not this function's: `use_experiment` sends the
    traces that follow to no run, and a run open at the time forgets its id
    and cannot be closed, found live on 2026-10-03.
    """
    tracker.start_trace(
        name=run_name(
            kind="search", values={"index": report.index, "label": label}, environ=environ
        ),
        tags=tracking_tags(kind="search", pipeline=pipeline, label=label, environ=environ),
        inputs={
            "query": report.query,
            "where": {name: list(values) for name, values in where.items()},
            # Whose search it was: the readers named, or `None` (R11.35).
            "readers": None if report.readers is None else list(report.readers),
        },
    )
    tracker.span(
        kind="embedding",
        name=report.model,
        attributes={
            "dossier.model": report.model,
            "dossier.text": report.embedded_as,
            # A cached vector cost nothing, and says so rather than nothing.
            "dossier.tokens": report.tokens or 0,
            "dossier.cached": report.cached,
        },
    )
    tracker.span(
        kind="retriever",
        name=f"search {report.index}",
        attributes={
            "dossier.results": [
                {
                    "rank": found.rank,
                    "document_id": found.document.document_id,
                    "chunk_id": found.ranked.candidate.chunk_id,
                    "score": found.ranked.score,
                    "meaning_rank": found.ranked.meaning,
                    "words_rank": found.ranked.words,
                }
                for found in report.found
            ],
        },
    )
    tracker.end_trace(
        status="OK", outputs=[found.document.document_id for found in report.found]
    )
