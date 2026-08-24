"""The folder connector: a local directory as a source (spec 001).

The simplest source there is, and the one that makes a manual drop replay like
any other. It has no version marker of its own, so change detection falls through
to payload hashing (R1.5, R2.2, R2.10).

It sits in this package because that is where connectors live, not because it
needs the network -- it does not touch it at all.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from dossier.domain.ports import AttachmentRef, ItemRef, RawItem


class FolderConnector:
    """Every file under a directory, keyed by its path relative to that root."""

    def __init__(self, path: Path) -> None:
        self._root = Path(path)

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        """Every file currently under the root, in a stable order.

        `since` is accepted and ignored. A folder records no reliable change
        time -- an mtime changes on copy and says nothing about content -- so the
        connector returns everything. Over-returning is always a legal answer;
        under-returning is a defect (R1.4).

        Sorted by key, because an unsorted directory listing is machine-dependent
        ordering and the ledger comparison downstream must not depend on the
        order items arrived in (R2.9).

        Sorted by the *key string* rather than by `Path`, which is not the same
        thing: `PurePath` comparison is case-insensitive on Windows and
        case-sensitive on Linux, so `sorted(paths)` puts `audit-note.pdf` before
        `INC-4821.md` on one platform and after it on the other. That is exactly
        the cross-machine variation R5.6 rules out.
        """
        if not self._root.is_dir():
            # An empty iterator, not an error: a source whose scope currently
            # matches nothing is a legitimate state (R1.3 example 3), and a
            # configured folder that has not been created yet is that same state.
            return

        keys = sorted(self._key(path) for path in self._root.rglob("*") if path.is_file())
        for key in keys:
            yield ItemRef(key=key, remote_version=None, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        """The file's bytes, unmodified.

        No decoding, no line-ending translation, no BOM stripping. Anything of
        that kind would change the content hash of every file it touched, and the
        stored snapshot must be what was actually there (R1.2).
        """
        path = self._resolve(key)
        return RawItem(
            key=key,
            payload=path.read_bytes(),
            media_type=self._media_type(path),
            remote_version=None,
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        """None, ever.

        A file in a folder carries nothing. Returning an empty iterator rather
        than raising keeps the caller free of per-connector special cases, which
        is the whole point of the interface (R1.7).
        """
        return iter(())

    def _key(self, path: Path) -> str:
        # Forward slashes regardless of platform: the key reaches the ledger and
        # from there a cache key, and R5.6 forbids a path that differs between
        # a developer's machine and CI.
        return path.relative_to(self._root).as_posix()

    def _resolve(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        root = self._root.resolve()
        if not candidate.is_relative_to(root):
            # A key is data from a listing, and a listing is data from outside.
            # `../../.env` must not be fetchable through a source that was
            # configured to expose one directory.
            raise ValueError(f"{key!r} resolves outside the source directory")
        return candidate

    @staticmethod
    def _media_type(path: Path) -> str:
        media_type, _ = mimetypes.guess_type(path.name)
        return media_type or "application/octet-stream"

    @classmethod
    def from_config(cls, config, *, workspace: Path) -> FolderConnector:
        """Build from a `sources.yaml` entry (the entry-point contract).

        `path` is resolved against the workspace, so a configuration file is
        portable and a relative path in it means the same thing wherever the
        workspace is checked out.
        """
        if config.path is None:
            raise ValueError(
                f"source {config.id!r} has type 'folder' and no `path`. "
                "A folder source needs a directory to read."
            )
        return cls(Path(workspace) / config.path)
