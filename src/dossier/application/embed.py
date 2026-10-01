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
from pathlib import Path

from dossier.application.plan import latest_manifest
from dossier.application.run import recorded_failures
from dossier.domain.chunks import chunk_id
from dossier.domain.grounding import check_field
from dossier.domain.index import (
    Carried,
    Embedded,
    IndexDeclaration,
    IndexedChunk,
    IndexedDocument,
    LatestRun,
    carried,
    changes,
    document_id,
    embedding_text,
    indexed,
    mismatched_length,
    record_for,
    title_of,
    vector_column,
)
from dossier.domain.keys import embedding_key
from dossier.domain.ports import (
    ArtifactStore,
    Chunker,
    EmbeddingProvider,
    IndexSink,
    Tracker,
)
from dossier.domain.schemas import FieldRecord, StageOutput
from dossier.domain.store import RUNS_ROOT
from dossier.domain.tracking import label_for, run_name
from dossier.domain.tracking import tags as tracking_tags

# How many texts one request for vectors carries. A few dozen keeps a request
# small enough to retry and a CPU-bound model responsive; nothing depends on
# the number but how many requests a first build makes.
BATCH = 32
BODY = "body"
RECORD = "record"
# What renders a record chunk, as a chunker's identity names what cut a body
# chunk: moved whenever the rendering of `field: value` lines changes.
RECORD_CHUNKER = "record@1"


@dataclass(frozen=True)
class ToIndex:
    """One document the ledger holds active, and its converted text."""

    source_id: str
    key: str
    snapshot: str
    text: str


@dataclass(frozen=True)
class EmbedRequest:
    """One request for vectors: the chunks it was for, and what the model counted (R11.33)."""

    chunk_ids: tuple[str, ...]
    tokens: int | None


@dataclass(frozen=True)
class EmbedReport:
    """What one `dossier embed` did, in the counts its line prints (R18.7)."""

    index: str
    chunks: int
    embedded: int
    cached: int
    written: int
    removed: int
    # What the command says about a document beyond the counts: a record not
    # carried, or values left out of one (R18.8, R18.9). Printed before the line.
    notes: tuple[str, ...] = ()
    # Each request the model was sent, in order: a trace each (R11.33).
    requests: tuple[EmbedRequest, ...] = ()

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
    kind: str = BODY


def embed_index(
    *,
    declaration: IndexDeclaration,
    documents: Sequence[ToIndex],
    readers: Mapping[str, tuple[str, ...]],
    chunker: Chunker,
    embedder: EmbeddingProvider,
    vectors: ArtifactStore,
    sink: IndexSink,
    run: LatestRun | None = None,
    enums: Mapping[str, Sequence[str]] | None = None,
) -> EmbedReport:
    """Bring `declaration`'s index to exactly `documents`, asking only for missing vectors.

    Every vector is in hand and checked before the index is touched, so a
    refusal leaves it as it was (R18.5 row 5). A document's record is the
    latest run's, of the snapshot held (R18.8), its values checked as `eval`
    checks them before any is carried (R18.9).
    """
    model = declaration.embedding_model
    ordered = sorted(documents, key=lambda document: (document.source_id, document.key))
    asks = bool(declaration.fields.filter or declaration.fields.embed)
    notes: list[str] = []
    if asks and run is None:
        notes.append(f"no run of {declaration.pipeline} yet")
    cuts: dict[str, list[_Cut]] = {}
    records: dict[str, Carried] = {}
    for document in ordered:
        identity = document_id(document.source_id, document.key)
        cuts[identity] = _cut(document, chunker)
        if not asks:
            continue
        answered, note = record_for(document.key, held_snapshot=document.snapshot, run=run)
        if note is not None:
            notes.append(note)
        if answered is None:
            continue
        checked = [
            (
                record,
                check_field(
                    record, input_documents={document.key: document.text}, enums=enums
                ).verdict,
            )
            for record in answered
        ]
        records[identity] = carried(declaration.fields, checked)
        if (left_out := records[identity].note(document.key)) is not None:
            notes.append(left_out)
        if records[identity].record_text is not None:
            cuts[identity].append(
                _record_cut(
                    identity,
                    records[identity].record_text,
                    at=len(cuts[identity]),
                    embedded=declaration.fields.embed,
                )
            )
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
    requests: list[EmbedRequest] = []
    for start in range(0, len(missing), BATCH):
        batch = missing[start : start + BATCH]
        replies = embedder.embed(batch)
        asked = set(batch)
        requests.append(
            EmbedRequest(
                chunk_ids=tuple(cut.chunk_id for cut in every if cut.embedded_as in asked),
                tokens=getattr(embedder, "last_tokens", None),
            )
        )
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
            run_id=run.run_id if run is not None and identity in records else None,
            values=records[identity].values if identity in records else None,
            chunks=[
                Embedded(
                    chunk_id=cut.chunk_id,
                    kind=cut.kind,
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
        notes=tuple(notes),
        requests=tuple(requests),
    )


def _record_cut(identity: str, text: str, *, at: int, embedded: Sequence[str]) -> _Cut:
    """The record chunk: the run's grounded free text, filed after the body (R18.9).

    Its id names what made it, as a body chunk's names its chunker (R18.2): the
    fields it renders, so carrying another field re-files it.
    """
    return _Cut(
        document=identity,
        chunk_id=chunk_id(
            document_id=identity,
            chunker=RECORD_CHUNKER,
            settings={"embed": list(embedded)},
            index=at,
            text=text,
        ),
        chunk_index=at,
        heading_path=(),
        text=text,
        embedded_as=text,
        kind=RECORD,
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


def read_latest_run(workspace: Path, pipeline: str, step: str) -> LatestRun | None:
    """What the pipeline's latest run read, failed and answered at `step` (R18.8).

    The latest is found as `eval` and `status` find it (R16.2). Its pins come
    from its manifest, its failures from `failures.json` (R4.27), and its
    answers from the step's files under `runs/` (R0.11), so nothing is asked
    of a model to learn them. A document two steps failed is named by the
    first, as the run met it.
    """
    plan, run_dir = latest_manifest(workspace / RUNS_ROOT, pipeline)
    if plan is None or run_dir is None:
        return None
    directory = workspace / RUNS_ROOT / run_dir
    failed: dict[str, str] = {}
    for failure in recorded_failures(directory) or []:
        failed.setdefault(str(failure["document"]), str(failure["step"]))
    answers: dict[str, tuple[FieldRecord, ...]] = {}
    for document in plan.documents:
        filed = directory / step / f"{document.key}.json"
        # A `per_part` step files each part under its document (R0.13).
        parts = sorted((directory / step / document.key).glob("*.json"))
        if filed.is_file():
            parts = [filed]
        if parts:
            answers[document.key] = tuple(
                record
                for part in parts
                for record in StageOutput.model_validate_json(
                    part.read_text(encoding="utf-8")
                ).fields
            )
    return LatestRun(
        run_id=run_dir,
        pinned={document.key: document.snapshot for document in plan.documents},
        failed=failed,
        records=answers,
    )


def record_embed(
    tracker: Tracker,
    *,
    experiment: str,
    declaration: IndexDeclaration,
    report: EmbedReport,
    started: str,
    environ: Mapping[str, str],
    dossier_version: str,
) -> bool:
    """Record an `embed` that changed the index as one MLflow run, or nothing (R11.33).

    Opened once the index is written, as `gc`'s record is once the deleting is
    done: what it records are the counts the line printed. Each request for
    vectors is a model call, and a trace. An `embed` that wrote and removed
    nothing changed nothing, and records nothing, as a `gc` that found nothing
    to delete does. Answers whether it recorded.
    """
    if not (report.written or report.removed):
        return False
    label = label_for(None, environ)
    tracker.start_run(
        experiment=experiment,
        name=run_name(
            kind="embed",
            values={"index": declaration.name, "started": started, "label": label},
            environ=environ,
        ),
        tags=tracking_tags(
            kind="embed", pipeline=declaration.pipeline, label=label, environ=environ
        ),
    )
    params = {"index": declaration.name, "embedding_model": declaration.embedding_model}
    if dossier_version:
        params["dossier_version"] = dossier_version
    tracker.log_params(params)
    tracker.log_metrics(
        {
            "chunks": report.chunks,
            "embedded": report.embedded,
            "cached": report.cached,
            "written": report.written,
            "removed": report.removed,
        }
    )
    for at, asked in enumerate(report.requests, start=1):
        tracker.start_trace(
            name=f"embed {declaration.name} · request {at}",
            tags={"dossier.kind": "embed"},
            inputs={"chunks": list(asked.chunk_ids)},
        )
        tracker.span(
            kind="embedding",
            name=declaration.embedding_model,
            attributes={
                "dossier.model": declaration.embedding_model,
                "dossier.chunks": list(asked.chunk_ids),
                "dossier.tokens": asked.tokens,
            },
        )
        tracker.end_trace(status="OK")
    tracker.describe(report.line)
    tracker.end_run(status="FINISHED")
    return True
