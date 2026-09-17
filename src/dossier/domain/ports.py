"""The interfaces the outside world is reached through (spec 001).

Protocols and value objects only -- pure types, no behaviour, no IO. They live in
`domain/` so that `application/` can depend on them without depending on any
implementation, which is what lets every use case run against a fake.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class ItemRef(BaseModel):
    """One item as it appears in a listing."""

    model_config = ConfigDict(frozen=True)

    key: str
    remote_version: str | None = None
    updated_at: datetime | None = None


class RawItem(BaseModel):
    """One item's payload, exactly as received (R1.2)."""

    model_config = ConfigDict(frozen=True)

    key: str
    payload: bytes
    media_type: str
    remote_version: str | None = None


class AttachmentRef(BaseModel):
    """A file carried by an item, addressed and versioned independently (R1.6)."""

    model_config = ConfigDict(frozen=True)

    key: str
    item_key: str
    remote_version: str | None = None


@runtime_checkable
class Connector(Protocol):
    """The three questions every source type answers.

    Implementations live in `dossier.infrastructure.connectors`, the only package
    permitted to touch the network (R0.1), and are discovered through the
    `dossier.connectors` entry point group rather than named anywhere in the core
    package (R1.7).
    """

    def list(self, since: datetime | None) -> Iterator[ItemRef]:
        """Every item currently in scope.

        When `since` is given the connector MAY restrict the result to items
        changed at or after it. Returning more than asked for is always allowed;
        returning less is a defect that presents as a document silently going
        stale (R1.4).
        """
        ...

    def fetch(self, key: str) -> RawItem:
        """The full payload of one item, byte-for-byte as received (R1.2)."""
        ...

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        """Files attached to the item, each independently addressable (R1.6)."""
        ...


@runtime_checkable
class ModelClient(Protocol):
    """How a stage reaches a model.

    Declared here so that `application/` can run a stage without importing any
    vendor SDK, and so the default test suite can hand it a fake that counts
    calls -- R4.6, R5.5 and R5.7 are all claims about how many calls happened.

    `model_id` is on the client rather than passed per call because it is part of
    every cache key (R5.3) and part of every provenance record (R0.3): a score
    without the model that produced it is not reproducible.
    """

    model_id: str

    def complete(self, prompt: str, *, schema: dict | None = None) -> str:
        """One completion, returned as text for the caller to validate."""
        ...


@runtime_checkable
class Tracker(Protocol):
    """Where a command's record is sent (spec 010, spec 011).

    Every method **sends and returns nothing**. That is the whole of R0.10's
    third package: tracking only reports, so nothing MLflow holds can enter a
    key, a manifest or a score, and a run is reproducible whether tracking is on
    or off (R10.4). A method that returned something read from the server would
    be the first way for it to become an input.

    Declared here so that `application/` records without importing MLflow, and
    so the default suite can hand it a `FakeTracker` that counts runs, traces and
    spans -- R11.1 and R11.2 are claims about how many were recorded.

    A run holds traces; a trace is one (step, document), the unit of a cache key
    (spec 011), and holds spans.
    """

    def start_run(self, *, experiment: str, name: str, tags: Mapping[str, str]) -> None: ...

    def log_params(self, params: Mapping[str, str]) -> None: ...

    def log_metrics(self, metrics: Mapping[str, float]) -> None: ...

    def log_artifact(self, name: str, content: bytes) -> None: ...

    def start_trace(self, *, name: str, tags: Mapping[str, str]) -> None: ...

    def span(self, *, kind: str, name: str, attributes: Mapping[str, object]) -> None: ...

    def end_trace(self, *, status: str, error: str | None = None) -> None: ...

    def end_run(self, *, status: str) -> None: ...


@runtime_checkable
class Converter(Protocol):
    """Turning one snapshot into one artifact a stage can read (spec 008).

    The four identity attributes are not decoration. `media_type` and `kind` are
    the pair a converter is selected by (R8.3); `id` and `version` enter every
    convert key and every provenance record, so raising the version invalidates
    exactly the artifacts this converter produced and nothing else (R5.4, R8.2).

    The obligation on an author is precise and no test can enforce it: **raise
    `version` whenever output could change for the same input.** A converter that
    improves without doing so leaves a cache full of artifacts claiming to be
    something they are not, and nothing anywhere will notice.
    """

    id: str
    version: str
    media_type: str
    kind: str

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The artifact, as a pure function of `payload` and `options` (R8.1).

        Reads nothing else: no clock, no locale, no environment variable, no file
        outside its input, and no network (R0.1). `K_convert` claims the artifact
        is determined by the snapshot hash, this converter's id and version, and
        these options; a converter consulting anything else makes that key a lie
        and the cache serves text nothing can detect as stale.
        """
        ...


@runtime_checkable
class SnapshotReader(Protocol):
    """Reading back what the store holds, by content hash.

    Read-only on purpose. A use case that could write to the snapshot store
    could break R0.2 by accident, and no caller right of the hash boundary has
    any business storing a snapshot.
    """

    def get(self, digest: str) -> bytes:
        """The stored bytes, or `FileNotFoundError` naming the hash."""
        ...

    def exists(self, digest: str) -> bool:
        """Whether the store holds `digest`; a read, so a replay may ask (R4.7 row 4)."""
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Where a computed artifact is kept against the key that describes it.

    A cache and never a source of truth (R5.9): a miss is the normal case, so
    `get` answers `None` rather than raising, and nothing may treat what comes
    back as authority for anything except "this work was already done".
    """

    def get(self, key: str, *, require_record: bool = False) -> bytes | None:
        """The artifact, or `None`. With `require_record`, a hit needs its record.

        An artifact whose provenance record is missing is not a cache entry: the
        process was killed between the two writes, and nothing can say what
        produced those bytes (R0.3, R5.8).
        """
        ...

    def put(self, key: str, payload: bytes, *, record: dict | None = None) -> None: ...


@runtime_checkable
class SnapshotWriter(Protocol):
    """Storing and reading back snapshots, for the one use case that stores them.

    Deliberately separate from `SnapshotReader`. Only `sync` writes snapshots;
    everything right of the hash boundary reads. Handing convert or run a type
    with `put` on it would be handing them a way to break R0.2 by accident.
    """

    def put(self, payload: bytes) -> str: ...

    def get(self, digest: str) -> bytes: ...

    def exists(self, digest: str) -> bool: ...


@runtime_checkable
class LedgerWriter(Protocol):
    """What `sync` needs of a ledger.

    Named so the seam is checkable rather than conventional: `sync_source` takes
    its store and its ledger as arguments and constructs neither, which is what
    lets the whole use case run against fakes -- and those two parameters were the
    ones with no type.
    """

    def rows(self, source_id: str) -> list: ...

    def row(self, source_id: str, key: str): ...

    def record(self, row) -> None: ...

    def touch(self, source_id: str, key: str, *, seen_at: datetime) -> None: ...

    def set_state(self, source_id: str, keys: Iterable[str], state) -> None: ...

    def set_watermark(self, source_id: str, when: datetime) -> None: ...

    def config_hash(self, source_id: str) -> str | None: ...

    def set_config_hash(self, source_id: str, value: str) -> None: ...
