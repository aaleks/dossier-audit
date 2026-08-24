"""R1.5 — a connector that cannot supply `remote_version` sets it to `None`.

A fabricated version marker is worse than none: it makes R2.1 skip a fetch for an
item that did change.

Proved here for the `folder` connector. The Confluence `v37` row (example 2) and
the Jira missing-field row (example 3) belong to connectors that do not exist
yet -- which is why this rule stays NOT MET.
"""

from __future__ import annotations

import os
from pathlib import Path

from dossier.domain.sync import needs_fetch
from dossier.infrastructure.connectors.folder import FolderConnector


class TestFolderHasNoVersionMarker:
    """R1.5 — saying nothing is better than saying something wrong."""

    def test_a_listed_item_has_no_remote_version(self, tmp_path: Path):
        """Example 1: the one where a folder admits it does not know."""
        (tmp_path / "audit-note.pdf").write_bytes(b"x")

        (ref,) = FolderConnector(tmp_path).list(None)

        assert ref.remote_version is None

    def test_a_fetched_item_has_no_remote_version(self, tmp_path: Path):
        """The same claim on the other half of the interface."""
        (tmp_path / "audit-note.pdf").write_bytes(b"x")

        assert FolderConnector(tmp_path).fetch("audit-note.pdf").remote_version is None

    def test_the_file_mtime_is_not_used_as_a_version_marker(self, tmp_path: Path):
        """Counter-example (row 4): the one where mtime looks useful and is not.

        An mtime changes on copy and says nothing about content. Using it would
        make R2.1 skip a fetch for a file whose bytes really did change -- for
        instance one restored from a backup with its timestamp preserved.
        """
        note = tmp_path / "audit-note.pdf"
        note.write_bytes(b"original")
        old = (note.stat().st_atime, note.stat().st_mtime)

        note.write_bytes(b"edited, and then the timestamp put back")
        os.utime(note, times=old)

        (ref,) = FolderConnector(tmp_path).list(None)

        assert ref.remote_version is None
        assert ref.updated_at is None

    def test_no_version_marker_means_the_payload_is_always_fetched(self, tmp_path: Path):
        """The one that shows why `None` is the safe answer.

        R2.1 can only skip when both markers are present and equal. `None` sends
        every item through to the content hash, which is the decision a folder
        source can actually make correctly (R2.2, R2.10).
        """
        (tmp_path / "audit-note.pdf").write_bytes(b"x")

        (ref,) = FolderConnector(tmp_path).list(None)

        assert needs_fetch(recorded_version=None, listed_version=ref.remote_version)

    def test_an_empty_string_is_not_used_in_place_of_none(self, tmp_path: Path):
        """The one where a falsy placeholder would compare equal to itself.

        Two items both carrying `""` would look unchanged to R2.1 forever.
        """
        (tmp_path / "audit-note.pdf").write_bytes(b"x")

        (ref,) = FolderConnector(tmp_path).list(None)

        assert ref.remote_version is None, "absence must be None, not a falsy placeholder"
