"""The immutable snapshot store (R0.2).

Content-addressed, append-only, and offering no way to delete. The store gains
content and never loses or changes any: that is what lets a run from six months
ago resolve the documents it read (R2.7, R4.9).

The path layout is decided in `dossier.domain.store`; this module only puts bytes
where that function says, and reads them back.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dossier.domain.hashing import content_hash, short
from dossier.domain.store import SNAPSHOT_ROOT, snapshot_path


class SnapshotStore:
    """Bytes on disk, addressed by what they contain.

    Deliberately has no `delete`, `remove` or `prune`. R0.2 says nothing is ever
    removed, and the cheapest way to hold that is to offer no operation that
    could -- so it cannot happen by accident and no reviewer has to check every
    call site for it.
    """

    def __init__(self, workspace: Path) -> None:
        self._root = Path(workspace) / SNAPSHOT_ROOT

    def put(self, payload: bytes) -> str:
        """Store `payload` if it is not already held, and return its digest."""
        digest = content_hash(payload)
        destination = self._path(digest)

        if destination.exists():
            # Already held. Returning without touching the file is not just an
            # optimisation: rewriting identical bytes would still be a write to
            # a stored snapshot, which is what R0.2 forbids.
            return digest

        destination.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomically(destination, payload)
        return digest

    def get(self, digest: str) -> bytes:
        path = self._path(digest)
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            # Named in the message because this is where a replay of a run whose
            # snapshot has gone missing begins to fail, and R4.7 requires that
            # failure to be clear rather than a silent substitution.
            raise FileNotFoundError(f"no snapshot for {short(digest)}... at {path}") from error

    def exists(self, digest: str) -> bool:
        return self._path(digest).exists()

    def _path(self, digest: str) -> Path:
        return self._root / snapshot_path(digest)

    @staticmethod
    def _write_atomically(destination: Path, payload: bytes) -> None:
        """Write via a temporary name and rename into place.

        An interruption then leaves either nothing or a complete snapshot, never
        a truncated file sitting at a content-addressed path whose name promises
        bytes it does not contain (R2.8).

        The temporary file is created in the destination directory so the rename
        stays on one filesystem, where it is atomic.
        """
        handle, temporary_name = tempfile.mkstemp(dir=destination.parent, suffix=".part")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
