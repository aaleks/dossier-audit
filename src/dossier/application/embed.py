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

from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.plan import latest_manifest
from dossier.application.run import (
    MissingFromReplay,
    recorded_failures,
    replay,
    replayed_inputs,
    replayed_parts,
)
from dossier.domain.chunks import chunk_id, record_chunk_id
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
    SnapshotReader,
    Tracker,
)
from dossier.domain.store import RUNS_ROOT
from dossier.domain.tracking import label_for, run_name
from dossier.domain.tracking import tags as tracking_tags

# How many texts one request for vectors carries. A few dozen keeps a request
# small enough to retry and a CPU-bound model responsive; nothing depends on
# the number but how many requests a first build makes.
BATCH = 32
BODY = "body"
RECORD = "record"


@dataclass(frozen=True)
class ToIndex:
    """One document the ledger holds active, and its converted text."""

    source_id: str
    key: str
    snapshot: str
    text: str


@dataclass(frozen=True)
class Unconverted:
    """A document the ledger holds active whose conversion failed at this embed (R18.4)."""

    source_id: str
    key: str
    reason: str


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
    unconverted: Sequence[Unconverted] = (),
) -> EmbedReport:
    """Bring `declaration`'s index to exactly `documents`, asking only for missing vectors.

    Every vector is in hand and checked before the index is touched, so a
    refusal leaves it as it was (R18.5 row 5). A document's record is the
    latest run's, of the snapshot held (R18.8), its values checked as `eval`
    checks them before any is carried (R18.9).
    """
    model = declaration.embedding_model
    ordered = sorted(documents, key=lambda document: (document.source_id, document.key))
    asks = declaration.fields.carried
    notes: list[str] = []
    if asks and run is None:
        notes.append(f"no run of {declaration.pipeline} yet")
    elif asks and run.unreplayable is not None:
        notes.append(f"no record: {run.run_id} cannot be replayed: {run.unreplayable}")
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
        records[identity] = carried(declaration.fields, checked, enums=enums)
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
        vector = cached_vector(vectors, model, text)
        if vector is None:
            missing.append(text)
        else:
            held_vectors[text] = vector
    cached = sum(1 for cut in every if cut.embedded_as in held_vectors)

    answered: dict[str, tuple[float, ...]] = {}
    requests: list[EmbedRequest] = []
    try:
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
    except Exception:
        # Stopped by a failed request: what was answered before it is kept, so
        # the next embed asks only for the rest (R18.12). Only when its lengths
        # agree with each other and with the cache: a vector of the wrong
        # length, cached, would be served as if it were right (R18.5 row 5).
        known = held_vectors | answered
        if answered and (
            mismatched_length(
                [
                    (cut.document, cut.chunk_id, len(known[cut.embedded_as]))
                    for cut in every
                    if cut.embedded_as in known
                ]
            )
            is None
        ):
            for text, vector in answered.items():
                keep_vector(vectors, model, text, vector)
        raise
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
        keep_vector(vectors, model, text, vector)

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
    # What the ledger holds and this embed could not read keeps its last rows,
    # and is named (R18.4 row 6).
    for failed in unconverted:
        notes.append(f"{failed.key}: not converted, its rows are kept: {failed.reason}")
    write, remove = changes(
        sink.held(declaration.name),
        {identity: written[0].content_hash for identity, written in rows.items()},
        keep={document_id(failed.source_id, failed.key) for failed in unconverted},
    )
    for identity in write:
        document, chunks = rows[identity]
        sink.write(declaration.name, document, chunks)
    if remove:
        sink.remove(declaration.name, remove)

    return EmbedReport(
        index=declaration.name,
        chunks=len(every),
        # Chunks, as `chunks` and `cached` are: two chunks of one text are two
        # chunks embedded by one answer (R18.7 row 1).
        embedded=sum(1 for cut in every if cut.embedded_as in answered),
        cached=cached,
        written=len(write),
        removed=len(remove),
        notes=tuple(notes),
        requests=tuple(requests),
    )


def _record_cut(identity: str, text: str, *, at: int, embedded: Sequence[str]) -> _Cut:
    """The record chunk: the run's grounded free text, filed after the body (R18.9).

    Its id is the domain's: what rendered it and the fields it renders.
    """
    return _Cut(
        document=identity,
        chunk_id=record_chunk_id(document_id=identity, embedded=embedded, index=at, text=text),
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


def read_latest_run(
    workspace: Path,
    pipeline: str,
    step: str,
    *,
    store: SnapshotReader,
    converted: ArtifactStore,
    stage: ArtifactStore,
    masks: ArtifactStore | None = None,
    unreadable: list[tuple[str, str]] | None = None,
    stopped: list[str] | None = None,
) -> LatestRun | None:
    """What the pipeline's latest run that finished read, failed and answered at `step` (R18.8).

    A newer manifest that cannot be read is passed over, and put in
    `unreadable` for the command to name (R4.30); so is a newer run that
    stopped before it ended, in `stopped`: it never asked about some
    documents, and cannot be reproduced (R4.33).

    The latest is found as `eval` and `status` find it (R16.2). Its pins come
    from its manifest and its failures from `failures.json` (R4.27). Its
    answers are reproduced from the manifest and the cache, as `eval` reads
    them (R4.7, R7.10), and never from the copies under `runs/`: those are for
    people, who may edit them, and a copy read back would carry an answer
    `eval` never scored (R0.11, R18.8 row 8). Nothing is asked of a model. A
    run that cannot be reproduced carries nothing, and says why (row 7).
    """
    plan, run_dir = latest_manifest(
        workspace / RUNS_ROOT,
        pipeline,
        unreadable=unreadable,
        stopped=[] if stopped is None else stopped,
    )
    if plan is None or run_dir is None:
        return None
    directory = workspace / RUNS_ROOT / run_dir
    recorded = recorded_failures(directory)
    failed: dict[str, str] = {}
    for failure in recorded or []:
        failed.setdefault(str(failure["document"]), str(failure["step"]))
    pinned = {document.key: document.snapshot for document in plan.documents}
    manifest = Manifest.read(directory / MANIFEST_NAME)
    try:
        report = replay(
            manifest=manifest,
            document_text=replayed_inputs(manifest, store=store, cache=converted, masks=masks),
            document_parts=replayed_parts(manifest, store=store, cache=converted),
            cache=stage,
            failures=recorded,
        )
    except MissingFromReplay as error:
        return LatestRun(
            run_id=run_dir,
            pinned=pinned,
            failed=failed,
            records={},
            unreplayable=" ".join(str(error).split()),
        )
    answers = {
        result.document: result.records
        for done in report.steps
        if done.step == step
        for result in done.results
        if not result.failed
    }
    return LatestRun(run_id=run_dir, pinned=pinned, failed=failed, records=answers)


def record_embed(
    tracker: Tracker,
    *,
    experiment: str,
    declaration: IndexDeclaration,
    report: EmbedReport,
    started: str,
    environ: Mapping[str, str],
    dossier_version: str,
    label: str = "",
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
    label = label_for(label, environ)
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


def cached_vector(vectors: ArtifactStore, model: str, text: str) -> tuple[float, ...] | None:
    """The vector the cache holds for `text` embedded by `model`, or `None` (R18.3, R19.3)."""
    return _read_vector(vectors.get(embedding_key(model, text), require_record=True))


def keep_vector(vectors: ArtifactStore, model: str, text: str, vector: Sequence[float]) -> None:
    """Cache `vector` as `model`'s for `text`, keyed by the two (R18.3, R19.3)."""
    vectors.put(
        embedding_key(model, text),
        json.dumps(list(vector)).encode("utf-8"),
        record={"embedding_model": model, "dimensions": len(vector)},
    )


def _read_vector(found: bytes | None) -> tuple[float, ...] | None:
    """A cached vector, or `None` for one missing or unreadable (R18.3).

    The cache is never a source of truth (R5.9): an entry that cannot be read
    is a miss, asked for again, not a refusal of the whole embed.
    """
    if found is None:
        return None
    try:
        read = json.loads(found)
    except ValueError:
        return None
    if not isinstance(read, list) or not all(isinstance(value, int | float) for value in read):
        return None
    return tuple(float(value) for value in read)
