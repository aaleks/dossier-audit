"""R1.3 — `list(since=None)` returns every item currently in scope.

The full listing is what tombstoning is computed against, so an omission is
silently destructive.

Proved here for the `folder` connector. Jira pagination (example 2) is
implemented in `jira.py` and not transcribed here yet.
"""

from __future__ import annotations

from pathlib import Path

from dossier.domain.ports import ItemRef
from dossier.infrastructure.connectors.folder import FolderConnector


def populate(root: Path, names: list[str]) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"content of " + name.encode())


class TestFolderListing:
    """R1.3 — everything in scope, every time."""

    def test_every_file_in_the_folder_is_listed(self, tmp_path: Path):
        """The one where three files are three items.

        Example 1: `audit-note.pdf` and two others.
        """
        populate(tmp_path, ["audit-note.pdf", "INC-4821.md", "INC-4822.md"])

        keys = [ref.key for ref in FolderConnector(tmp_path).list(None)]

        assert keys == ["INC-4821.md", "INC-4822.md", "audit-note.pdf"]

    def test_nested_files_are_listed_with_posix_keys(self, tmp_path: Path):
        """The one where a subdirectory is still in scope.

        Keys use forward slashes on every platform: a key reaches the ledger and
        from there a cache key, and R5.6 forbids a path that differs between a
        developer's machine and CI.
        """
        populate(tmp_path, ["2026/q3/INC-4821.md"])

        keys = [ref.key for ref in FolderConnector(tmp_path).list(None)]

        assert keys == ["2026/q3/INC-4821.md"]

    def test_a_source_matching_nothing_is_empty_not_an_error(self, tmp_path: Path):
        """Example 3: the one where the folder is empty."""
        assert list(FolderConnector(tmp_path).list(None)) == []

    def test_a_folder_that_does_not_exist_yet_is_empty_not_an_error(self, tmp_path: Path):
        """The same state, reached a different way.

        A configured folder nobody has created is a source that currently matches
        nothing, which R1.3 example 3 says is legitimate.
        """
        assert list(FolderConnector(tmp_path / "inbox").list(None)) == []

    def test_directories_are_not_items(self, tmp_path: Path):
        """The one where only files are addressable."""
        populate(tmp_path, ["2026/q3/INC-4821.md"])

        refs = list(FolderConnector(tmp_path).list(None))

        assert [ref.key for ref in refs] == ["2026/q3/INC-4821.md"]

    def test_the_order_is_stable(self, tmp_path: Path):
        """The one where two listings agree.

        An unsorted directory listing is machine-dependent ordering, and R2.9
        requires two syncs over an unchanged source to produce identical ledger
        content.
        """
        populate(tmp_path, ["c.md", "a.md", "b.md"])
        connector = FolderConnector(tmp_path)

        assert [r.key for r in connector.list(None)] == [r.key for r in connector.list(None)]

    def test_since_may_be_ignored_and_still_return_everything(self, tmp_path: Path):
        """Counter-example (R1.4 row 4): the one where over-returning is correct.

        A folder records no reliable change time, so it returns everything
        regardless of `since`. A superset is always a legal answer; a subset is
        the defect.
        """
        from datetime import UTC, datetime

        populate(tmp_path, ["INC-4821.md", "INC-4822.md"])

        everything = list(FolderConnector(tmp_path).list(None))
        with_since = list(FolderConnector(tmp_path).list(datetime(2099, 1, 1, tzinfo=UTC)))

        assert [r.key for r in with_since] == [r.key for r in everything]

    def test_a_listing_yields_item_refs(self, tmp_path: Path):
        """The one where the interface is honoured, not approximated."""
        populate(tmp_path, ["INC-4821.md"])

        (ref,) = FolderConnector(tmp_path).list(None)

        assert isinstance(ref, ItemRef)
