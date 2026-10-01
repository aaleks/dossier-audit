"""The embedding index: what it is declared as, and what it carries (spec 018).

Everything here is a decision about the index, made from what was read: the
declaration, a pipeline's field kinds. Nothing here opens a file or reaches
the index. The index itself is derived data, rebuilt from the workspace
(R18.4), so every decision about what goes into it lives here, where it can
be proved without a database.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from dossier.domain.hashing import content_hash
from dossier.domain.scoring import FieldKind


class ChunkerSettings(BaseModel):
    """Which chunker cuts the documents, and with what (R18.1, R18.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    max_chars: int = Field(gt=0)


class IndexFields(BaseModel):
    """The fields of the pipeline's output the index carries (R18.9, R18.10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Exact values to filter on: a category is exact, and a vector would only
    # blur it.
    filter: tuple[str, ...] = ()
    # Free text, embedded in the document's record chunk.
    embed: tuple[str, ...] = ()


class IndexTarget(BaseModel):
    """Where the index is written. The connection string is a secret, so only
    the name of the variable holding it is written down (R1.8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dsn_env: str


class IndexDeclaration(BaseModel):
    """`indexes/<name>.yaml`: one index over one pipeline (spec 018)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # From the file's name, as a pipeline's is from its directory's.
    name: str
    pipeline: str
    embedding_model: str
    chunker: ChunkerSettings
    fields: IndexFields = IndexFields()
    target: IndexTarget


def field_refusals(
    fields: IndexFields, kinds: Mapping[str, FieldKind], *, declared_in: str
) -> list[tuple[str, str]]:
    """Each field the index may not carry, as `(group, why)`, in the order written (R18.10).

    A filter is an exact value and an embedded field is free text: the two are
    searched in different ways, and a field in the wrong group is searched in
    the wrong one. A field the output does not declare is a column the run never
    fills, found only by someone wondering why a filter returns nothing.
    """
    refused: list[tuple[str, str]] = []
    declared = ", ".join(sorted(kinds))
    for group, names in (("filter", fields.filter), ("embed", fields.embed)):
        for name in names:
            kind = kinds.get(name)
            if kind is None:
                why = (
                    f"fields.{group} names {name!r}, which {declared_in} does not "
                    f"declare. It declares: {declared}"
                )
            elif group == "filter" and kind is FieldKind.FREE_TEXT:
                why = (
                    f"fields.filter names {name!r}, a free_text field: free text is "
                    "embedded, not filtered"
                )
            elif group == "embed" and kind is not FieldKind.FREE_TEXT:
                why = (
                    f"fields.embed names {name!r}, {_article(kind.value)} {kind.value} "
                    "field: a category is filtered, not embedded"
                )
            else:
                continue
            refused.append((group, why))
    return refused


def _article(word: str) -> str:
    return "an" if word[0] in "aeiou" else "a"


def unreadable(read: Sequence[str], readers: Mapping[str, tuple[str, ...] | None]) -> list[str]:
    """The sources an index reads that have declared no readers, in the order read (R18.6).

    `dossier` fetches no permissions. A source nobody decided about would be
    searchable by anyone who can query the index, so it is not indexed at all.
    """
    return [source for source in read if not readers.get(source)]


def document_id(source_id: str, key: str) -> str:
    """A document's id in the index: its source and its key, readable in a query.

    A source id holds no colon, so the first one always separates the two,
    whatever the key holds: a web page's key is its URL.
    """
    return f"{source_id}:{key}"


@dataclass(frozen=True)
class Embedded:
    """A chunk with its id and its vector, ready to be filed (R18.2, R18.3)."""

    chunk_id: str
    kind: str
    chunk_index: int
    heading_path: tuple[str, ...]
    text: str
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class IndexedChunk:
    """One row of `chunks`: what is searched, by meaning and by words."""

    chunk_id: str
    document_id: str
    kind: str
    chunk_index: int
    heading_path: tuple[str, ...]
    text: str
    # On the chunk as well as its document, so a search filters what it may
    # return without a join that a careless query could leave out (R18.6).
    acl: tuple[str, ...]
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class IndexedDocument:
    """One row of `documents`, and the hash of everything written for it (R18.4)."""

    document_id: str
    index: str
    source_id: str
    key: str
    title: str
    snapshot: str
    acl: tuple[str, ...]
    embedding_model: str
    content_hash: str


def indexed(
    *,
    index: str,
    source_id: str,
    key: str,
    title: str,
    snapshot: str,
    acl: tuple[str, ...],
    embedding_model: str,
    chunks: Sequence[Embedded],
) -> tuple[IndexedDocument, list[IndexedChunk]]:
    """A document's rows, each carrying its source's readers (R18.6).

    `content_hash` covers everything the rows say except the vectors, which are
    the pinned model's answer to the chunk texts it already covers. The index
    is rewritten for a document only when this hash moves (R18.4).
    """
    identity = document_id(source_id, key)
    written = {
        "acl": list(acl),
        "chunks": [
            [
                chunk.chunk_id,
                chunk.kind,
                chunk.chunk_index,
                list(chunk.heading_path),
                chunk.text,
            ]
            for chunk in chunks
        ],
        "embedding_model": embedding_model,
        "index": index,
        "key": key,
        "snapshot": snapshot,
        "source_id": source_id,
        "title": title,
    }
    document = IndexedDocument(
        document_id=identity,
        index=index,
        source_id=source_id,
        key=key,
        title=title,
        snapshot=snapshot,
        acl=acl,
        embedding_model=embedding_model,
        content_hash=content_hash(
            json.dumps(written, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ),
    )
    rows = [
        IndexedChunk(
            chunk_id=chunk.chunk_id,
            document_id=identity,
            kind=chunk.kind,
            chunk_index=chunk.chunk_index,
            heading_path=chunk.heading_path,
            text=chunk.text,
            acl=acl,
            embedding=chunk.embedding,
        )
        for chunk in chunks
    ]
    return document, rows
