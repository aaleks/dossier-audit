"""`dossier search`: the documents an index holds that answer a query (spec 019).

The index and the embedding model are handed in, as a run's model client is;
this module constructs neither. The model is asked only for the query's
vector, and only when the cache has none (R19.3). What the index answers is
ranked by `dossier.domain.search`, and reaches the terminal and MLflow and
nothing else: no key, manifest or score (R0.17).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dossier.application.embed import cached_vector, keep_vector
from dossier.domain.index import IndexDeclaration
from dossier.domain.ports import ArtifactStore, EmbeddingProvider, IndexSearch
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
    reader: str | None
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
    reader: str | None,
    limit: int,
    chunks: bool,
    embedder: EmbeddingProvider,
    vectors: ArtifactStore,
    index: IndexSearch,
    held: Mapping[str, str],
) -> SearchReport:
    """Search `declaration`'s index for `query` (spec 019).

    The index is asked which model it was embedded with before the model is
    asked anything: a query vector from another model is meaningless against
    it (R19.6). `held` is each document the ledger holds now, by id, with its
    snapshot, to say how many the index does not reflect (R19.7).
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
        words=query,
        where=where,
        reader=reader,
        candidates=CANDIDATES,
    )
    shown = listed(fused(meaning=lists.meaning, words=lists.words), limit=limit, chunks=chunks)
    return SearchReport(
        index=declaration.name,
        query=query,
        reader=reader,
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
