"""The interfaces the outside world is reached through (spec 001).

Protocols and value objects only -- pure types, no behaviour, no IO. They live in
`domain/` so that `application/` can depend on them without depending on any
implementation, which is what lets every use case run against a fake.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
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


@runtime_checkable
class ArtifactStore(Protocol):
    """Where a computed artifact is kept against the key that describes it.

    A cache and never a source of truth (R5.9): a miss is the normal case, so
    `get` answers `None` rather than raising, and nothing may treat what comes
    back as authority for anything except "this work was already done".
    """

    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, payload: bytes) -> None: ...
