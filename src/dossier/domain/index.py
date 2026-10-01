"""The embedding index: what it is declared as, and what it carries (spec 018).

Everything here is a decision about the index, made from what was read: the
declaration, a pipeline's field kinds. Nothing here opens a file or reaches
the index. The index itself is derived data, rebuilt from the workspace
(R18.4), so every decision about what goes into it lives here, where it can
be proved without a database.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from dossier.domain.grounding import FieldVerdict, enum_folded
from dossier.domain.hashing import content_hash
from dossier.domain.schemas import FieldRecord
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

    @property
    def carried(self) -> bool:
        """Whether the index carries anything of a run: decided here, once (R18.8)."""
        return bool(self.filter or self.embed)


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
    # The run whose record the document carries, and the grounded values to
    # filter on that it gave (R18.8, R18.9). `None` and empty when it carries none.
    run_id: str | None = None
    values: Mapping[str, object] = field(default_factory=dict)


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
    run_id: str | None = None,
    values: Mapping[str, object] | None = None,
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
        "run_id": run_id,
        "snapshot": snapshot,
        "source_id": source_id,
        "title": title,
        "values": dict(values or {}),
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
        run_id=run_id,
        values=dict(values or {}),
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


# pgvector indexes a `vector` of up to 2,000 dimensions, and a `halfvec` of up
# to 4,000 (R18.5).
VECTOR_LIMIT = 2000
HALFVEC_LIMIT = 4000


def vector_column(dimensions: int) -> str:
    """The pgvector type an index of `dimensions`-long vectors holds them as (R18.5).

    Full precision where pgvector can index it, half where only that fits.
    Qwen3-Embedding-4B answers 2,560 values from fp16 weights, so half
    precision loses nothing it had.
    """
    if dimensions <= VECTOR_LIMIT:
        return f"vector({dimensions})"
    if dimensions <= HALFVEC_LIMIT:
        return f"halfvec({dimensions})"
    raise ValueError(
        f"a vector of {dimensions} values: pgvector indexes a vector of up to 2,000 "
        "dimensions and a halfvec of up to 4,000, and no type indexes this"
    )


def mismatched_length(answered: Sequence[tuple[str, str, int]]) -> str | None:
    """Why the vectors of one `embed` cannot share an index, or `None` (R18.5 row 5).

    `answered` is `(document_id, chunk_id, length)` in the order chunks are
    filed. A vector of another length than the rest is another model's, and
    one index holds one model's vectors.
    """
    if not answered:
        return None
    # The length most vectors have: one odd vector is the odd one wherever it
    # sorts, and is the one named. A tie goes to the first chunk filed.
    lengths = [length for _, _, length in answered]
    expected = max(dict.fromkeys(lengths), key=lengths.count)
    for document, chunk, length in answered:
        if length != expected:
            return (
                f"{document}: chunk {chunk[:12]} was answered {length} values, and the "
                f"index holds vectors of {expected}. One index holds one model's "
                "vectors: nothing is written"
            )
    return None


def embedding_text(heading_path: Sequence[str], text: str) -> str:
    """What a chunk is embedded as: the headings above it, then its text (R18.3).

    So the chunk holding `CHF 48'200` is found as `INC-4821`'s impact, and not
    as a sentence about money with nothing to say whose.
    """
    if not heading_path:
        return text
    return " > ".join(heading_path) + "\n\n" + text


def title_of(text: str, key: str) -> str:
    """A document's title: its first top-level heading, or its key (R18.1 row 4)."""
    for line in text.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return key


def changes(
    held: Mapping[str, str], current: Mapping[str, str], *, keep: Collection[str] = ()
) -> tuple[list[str], list[str]]:
    """What to write and to remove, by document id, to bring the index to `current` (R18.4).

    `held` and `current` map each document to the hash of everything written
    for it. A document is written when its hash is new or moved, and removed
    when the ledger no longer holds it active. Both sorted, so two runs over
    the same holdings do the same thing in the same order.
    """
    write = sorted(
        document for document, hashed in current.items() if held.get(document) != hashed
    )
    # `keep` is what the ledger holds and this embed could not read: a document
    # whose conversion failed. Its last rows stay; removing them would take a
    # held document out of search over one converter's failure (R18.4 row 6).
    remove = sorted(set(held) - set(current) - set(keep))
    return write, remove


@dataclass(frozen=True)
class LatestRun:
    """What the pipeline's latest run read and answered, as `embed` needs it (R18.8).

    `pinned` is the snapshot the run read for each document (its manifest),
    `failed` the step that first failed each failed document (R4.27), and
    `records` the answers of the step whose output the index carries.
    """

    run_id: str
    pinned: Mapping[str, str]
    failed: Mapping[str, str]
    records: Mapping[str, Sequence[FieldRecord]]


def record_for(
    key: str, *, held_snapshot: str, run: LatestRun | None
) -> tuple[Sequence[FieldRecord] | None, str | None]:
    """The latest run's answers about `key`, or why there are none (R18.8).

    A run's answers describe the snapshot it read. Carried beside a newer one,
    they would describe text that is no longer there, so a record is carried
    only when the run read the snapshot the ledger holds now. With no run at
    all there is nothing to say per document: the command says it once.
    """
    if run is None:
        return None, None
    pinned = run.pinned.get(key)
    if pinned is None:
        return None, f"{key}: no record: {run.run_id} did not read it"
    if pinned != held_snapshot:
        return None, f"{key}: record stale: {run.run_id} read an earlier snapshot"
    if key in run.failed:
        return None, f"{key}: no record: failed at {run.failed[key]} in {run.run_id}"
    answered = run.records.get(key)
    if answered is None:
        return None, f"{key}: no record: {run.run_id} filed no answer for it"
    return answered, None


@dataclass(frozen=True)
class Carried:
    """What a document's record puts in the index (R18.9)."""

    # Each filter field's grounded value, or values when a field was answered
    # more than once, as a list field is.
    values: Mapping[str, object]
    # The record chunk's text: one `field: value` line per grounded text field,
    # or `None` when there is none to embed.
    record_text: str | None
    # How many values were not carried, by verdict.
    left_out: Mapping[str, int]

    def note(self, key: str) -> str | None:
        if not self.left_out:
            return None
        count = sum(self.left_out.values())
        reasons = ", ".join(sorted(self.left_out))
        return f"{key}: {count} value{'' if count == 1 else 's'} left out: {reasons}"


def carried(
    fields: IndexFields,
    checked: Sequence[tuple[FieldRecord, FieldVerdict]],
    *,
    enums: Mapping[str, Sequence[str]] | None = None,
) -> Carried:
    """The grounded values of `fields`, from records checked as `eval` checks them (R18.9).

    Only a `valid` record is carried: its value was found in the document.
    An `ungrounded` one is scored incorrect whatever it says (R7.4); a
    `described` one is evidence on a page a string search cannot read (R6.15),
    and so is not evidence here either. An abstention says the document states
    nothing, which is not a value and not a value left out.
    """
    values: dict[str, list[object]] = {}
    texts: dict[str, list[str]] = {}
    left_out: dict[str, int] = {}
    wanted = set(fields.filter) | set(fields.embed)
    for record, verdict in checked:
        if record.field not in wanted or verdict is FieldVerdict.ABSTAINED:
            continue
        if verdict is not FieldVerdict.VALID:
            left_out[verdict.value] = left_out.get(verdict.value, 0) + 1
            continue
        if record.field in fields.filter:
            values.setdefault(record.field, []).append(
                _declared(record.value, (enums or {}).get(record.field))
            )
        else:
            texts.setdefault(record.field, []).append(str(record.value))
    lines = [f"{field}: {text}" for field in fields.embed for text in texts.get(field, [])]
    return Carried(
        values={
            field: answered[0] if len(answered) == 1 else answered
            for field, answered in sorted(values.items())
        },
        record_text="\n".join(lines) if lines else None,
        left_out=left_out,
    )


def carried_output(steps: Sequence[object], *, pipeline: str) -> object:
    """The one step whose output an index carries, or `ValueError` saying how many (R18.10).

    Decided here, once, for the loader that refuses and the command that reads
    the run: one output, as `eval` scores one (R17.6 row 5). Carried from two,
    a field could hold either step's answer and nothing would say which.
    """
    declaring = [step for step in steps if getattr(step, "output", None) is not None]
    if len(declaring) != 1:
        raise ValueError(
            f"fields are carried from one output, and {len(declaring)} steps of "
            f"{pipeline} declare an output, as eval refuses it"
        )
    return declaring[0]


def _declared(value: object, declared: Sequence[str] | None) -> object:
    """An enum's value in the spelling its declaration writes (R18.9 row 5).

    The check let it through folded (R6.26), and eval scores it so. Carried as
    answered, a filter on the declared value would miss what was scored correct.
    A value no declared one folds to, or a field with none declared, is as given.
    """
    if not declared:
        return value
    spelled = {enum_folded(option): option for option in declared}
    return spelled.get(enum_folded(value), value)
