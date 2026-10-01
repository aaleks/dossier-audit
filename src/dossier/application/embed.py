"""`dossier embed`: a pipeline's documents into the embedding index (spec 018).

The index is derived data. Everything written to it is rebuilt from what the
workspace holds: the documents the ledger holds active, their converted text,
and a cache of vectors keyed by the pinned model and the text embedded. The
model is asked only for a text no vector is cached for (R18.3), and the index
is written only where a document changed (R18.4).

What to cut, what to key and what to write are the domain's decisions. This
module asks for the vectors it lacks, keeps them, and hands the rows over.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dossier.domain.chunks import chunk_id
from dossier.domain.index import (
    Embedded,
    IndexDeclaration,
    IndexedChunk,
    IndexedDocument,
    changes,
    document_id,
    embedding_text,
    indexed,
    mismatched_length,
    title_of,
    vector_column,
)
from dossier.domain.keys import embedding_key
from dossier.domain.ports import ArtifactStore, Chunker, EmbeddingProvider, IndexSink

# How many texts one request for vectors carries. A few dozen keeps a request
# small enough to retry and a CPU-bound model responsive; nothing depends on
# the number but how many requests a first build makes.
BATCH = 32
BODY = "body"


@dataclass(frozen=True)
class ToIndex:
    """One document the ledger holds active, and its converted text."""

    source_id: str
    key: str
    snapshot: str
    text: str


@dataclass(frozen=True)
class EmbedReport:
    """What one `dossier embed` did, in the counts its line prints (R18.7)."""

    index: str
    chunks: int
    embedded: int
    cached: int
    written: int
    removed: int

    @property
    def line(self) -> str:
        return (
            f"{self.index} · {self.chunks} chunks · {self.embedded} embedded · "
            f"{self.cached} cached · {self.written} written · {self.removed} removed"
        )


@dataclass(frozen=True)
class _Cut:
    """A chunk with its id and the text it is embedded as."""

    document: str
    chunk_id: str
    chunk_index: int
    heading_path: tuple[str, ...]
    text: str
    embedded_as: str


def embed_index(
    *,
    declaration: IndexDeclaration,
    documents: Sequence[ToIndex],
    readers: Mapping[str, tuple[str, ...]],
    chunker: Chunker,
    embedder: EmbeddingProvider,
    vectors: ArtifactStore,
    sink: IndexSink,
) -> EmbedReport:
    """Bring `declaration`'s index to exactly `documents`, asking only for missing vectors.

    Every vector is in hand and checked before the index is touched, so a
    refusal leaves it as it was (R18.5 row 5).
    """
    model = declaration.embedding_model
    ordered = sorted(documents, key=lambda document: (document.source_id, document.key))
    cuts = {
        document_id(document.source_id, document.key): _cut(document, chunker)
        for document in ordered
    }
    every = [cut for document_cuts in cuts.values() for cut in document_cuts]

    held_vectors: dict[str, tuple[float, ...]] = {}
    missing: list[str] = []
    for text in sorted({cut.embedded_as for cut in every}):
        found = vectors.get(embedding_key(model, text), require_record=True)
        if found is None:
            missing.append(text)
        else:
            held_vectors[text] = tuple(json.loads(found))
    cached = sum(1 for cut in every if cut.embedded_as in held_vectors)

    answered: dict[str, tuple[float, ...]] = {}
    for start in range(0, len(missing), BATCH):
        batch = missing[start : start + BATCH]
        replies = embedder.embed(batch)
        if len(replies) != len(batch):
            raise ValueError(
                f"{model} answered {len(replies)} vectors for {len(batch)} texts: "
                "each text is owed one, and nothing is written"
            )
        answered.update(zip(batch, (tuple(reply) for reply in replies), strict=True))
    vector_of = held_vectors | answered

    refused = mismatched_length(
        [(cut.document, cut.chunk_id, len(vector_of[cut.embedded_as])) for cut in every]
    )
    if refused is not None:
        raise ValueError(refused)
    column = vector_column(len(vector_of[every[0].embedded_as])) if every else None

    # Kept only once all of them have been checked: a vector of the wrong
    # length, cached, would be served to the next embed as if it were right.
    for text, vector in answered.items():
        vectors.put(
            embedding_key(model, text),
            json.dumps(list(vector)).encode("utf-8"),
            record={"embedding_model": model, "dimensions": len(vector)},
        )

    rows: dict[str, tuple[IndexedDocument, list[IndexedChunk]]] = {}
    for document in ordered:
        identity = document_id(document.source_id, document.key)
        rows[identity] = indexed(
            index=declaration.name,
            source_id=document.source_id,
            key=document.key,
            title=title_of(document.text, document.key),
            snapshot=document.snapshot,
            acl=readers[document.source_id],
            embedding_model=model,
            chunks=[
                Embedded(
                    chunk_id=cut.chunk_id,
                    kind=BODY,
                    chunk_index=cut.chunk_index,
                    heading_path=cut.heading_path,
                    text=cut.text,
                    embedding=vector_of[cut.embedded_as],
                )
                for cut in cuts[identity]
            ],
        )

    if column is not None:
        sink.prepare(declaration.name, column)
    write, remove = changes(
        sink.held(declaration.name),
        {identity: written[0].content_hash for identity, written in rows.items()},
    )
    for identity in write:
        document, chunks = rows[identity]
        sink.write(declaration.name, document, chunks)
    if remove:
        sink.remove(declaration.name, remove)

    return EmbedReport(
        index=declaration.name,
        chunks=len(every),
        embedded=len(missing),
        cached=cached,
        written=len(write),
        removed=len(remove),
    )


def _cut(document: ToIndex, chunker: Chunker) -> list[_Cut]:
    identity = document_id(document.source_id, document.key)
    return [
        _Cut(
            document=identity,
            chunk_id=chunk_id(
                document_id=identity,
                chunker=chunker.identity,
                settings=chunker.settings,
                index=piece.index,
                text=piece.text,
            ),
            chunk_index=piece.index,
            heading_path=piece.heading_path,
            text=piece.text,
            embedded_as=embedding_text(piece.heading_path, piece.text),
        )
        for piece in chunker.chunk(document.text)
    ]
