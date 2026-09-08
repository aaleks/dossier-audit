"""Artifacts kept against the key that describes them (spec 005).

Addressed by cache key rather than by content: two different computations can
produce identical bytes, and each still needs its own entry so that invalidating
one does not invalidate the other.

The cache is an optimisation and never a source of truth (R5.9). Deleting the
whole directory must change no output, which is why nothing here is ever read
back as authority -- only as a way to avoid doing work again.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

CACHE_ROOT = Path(".dossier") / "cache"


class ArtifactCache:
    """Bytes on disk, addressed by the key of the computation that made them."""

    def __init__(self, workspace: Path, *, namespace: str) -> None:
        # A namespace per kind of computation -- `convert`, later `stage` -- so a
        # convert key and a stage key can never collide even if some future
        # composition made them equal.
        self._root = Path(workspace) / CACHE_ROOT / namespace

    def get(self, key: str) -> bytes | None:
        """The artifact for `key`, or `None` if it was never stored.

        `None` rather than an exception: a miss is the normal case on a first run
        and is not a failure of anything.
        """
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key: str, payload: bytes) -> None:
        """Store `payload` under `key`, atomically.

        An interrupted write leaves nothing rather than a truncated file sitting
        at a key that promises a complete artifact -- which is what R5.8 means by
        "an interrupted stage leaves no cache entry".
        """
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)

        handle, temporary = tempfile.mkstemp(dir=str(destination.parent), suffix=".part")
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(payload)
            os.replace(temporary, destination)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _path(self, key: str) -> Path:
        # Fanned out two levels, as the snapshot store is: a directory holding
        # one entry per document per stage gets large enough to slow down on
        # some filesystems, and the fan-out costs nothing.
        return self._root / key[:2] / key[2:4] / key
