"""R0.2 — a stored snapshot is never modified or deleted in place.

Once written, the bytes at a snapshot path never change and the path is never
removed. New content means a new content-addressed path. Tombstoning marks the
ledger, never the store.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.domain.hashing import content_hash
from dossier.domain.store import SNAPSHOT_ROOT, snapshot_path
from dossier.infrastructure.store import SnapshotStore

INC_4821 = b"# INC-4821\n\ntotal exposure CHF 48'200\n"
INC_4821_REVISED = b"# INC-4821\n\ntotal exposure CHF 51'900\n"


class TestSnapshotStore:
    """R0.2 — the store only ever gains content."""

    def test_storing_identical_bytes_twice_does_not_write_again(self, tmp_path: Path):
        """The one where re-storing is genuinely free.

        Example 1. Asserted on the modification time rather than on the content:
        a store that rewrote the file with identical bytes would still violate
        the rule, and comparing content could not tell.
        """
        store = SnapshotStore(tmp_path)
        digest = store.put(INC_4821)

        before = (tmp_path / SNAPSHOT_ROOT / snapshot_path(digest)).stat().st_mtime_ns
        store.put(INC_4821)
        after = (tmp_path / SNAPSHOT_ROOT / snapshot_path(digest)).stat().st_mtime_ns

        assert before == after

    def test_changed_content_becomes_a_second_snapshot(self, tmp_path: Path):
        """Example 2: the one where the old bytes survive the new ones."""
        store = SnapshotStore(tmp_path)

        original = store.put(INC_4821)
        revised = store.put(INC_4821_REVISED)

        assert original != revised
        assert store.get(original) == INC_4821
        assert store.get(revised) == INC_4821_REVISED

    def test_a_stored_snapshot_stays_readable(self, tmp_path: Path):
        """Example 3: the one where a run from March still resolves.

        The store has no notion of scope and no notion of tombstoning -- that is
        the ledger's business (R2.7). Whatever the ledger later says about an
        item, the bytes remain.
        """
        store = SnapshotStore(tmp_path)
        digest = store.put(INC_4821)

        assert store.get(digest) == INC_4821
        assert store.exists(digest)

    def test_the_store_offers_no_way_to_delete(self, tmp_path: Path):
        """The one that makes the rule structural rather than a promise.

        R0.2 says nothing is ever deleted. The cheapest way to hold that is to
        give the type no operation that could -- so a caller cannot do it by
        accident, and a reviewer does not have to check every call site.
        """
        store = SnapshotStore(tmp_path)

        forbidden = {"delete", "remove", "unlink", "purge", "clear", "prune"}
        assert forbidden.isdisjoint(dir(store))

    def test_the_returned_digest_is_the_hash_of_what_was_stored(self, tmp_path: Path):
        """The one where the store cannot lie about what it holds."""
        store = SnapshotStore(tmp_path)

        digest = store.put(INC_4821)

        assert digest == content_hash(INC_4821)
        assert store.get(digest) == INC_4821

    def test_a_snapshot_lands_at_its_content_addressed_path(self, tmp_path: Path):
        """The one where R2.11's path function is the one actually used.

        Not a duplicate of R2.11: that rule proves the path is derived correctly,
        this proves the store honours it rather than inventing its own layout.
        """
        store = SnapshotStore(tmp_path)

        digest = store.put(INC_4821)

        assert (tmp_path / SNAPSHOT_ROOT / snapshot_path(digest)).read_bytes() == INC_4821

    def test_an_empty_payload_is_a_real_snapshot(self, tmp_path: Path):
        """The one where a zero-byte file is content, not an absence (R1.2)."""
        store = SnapshotStore(tmp_path)

        digest = store.put(b"")

        assert store.exists(digest)
        assert store.get(digest) == b""

    def test_reading_an_absent_snapshot_names_the_digest(self, tmp_path: Path):
        """Counter-example (row 4): the one where nothing was ever completed.

        A partially written snapshot never reaches its final path, so from a
        reader's side it simply is not there. R4.7 requires that a replay whose
        pinned snapshot is missing fails clearly rather than substituting other
        content, and this is where that error starts.
        """
        store = SnapshotStore(tmp_path)
        missing = content_hash(b"never stored")

        with pytest.raises(FileNotFoundError) as error:
            store.get(missing)

        assert missing[:8] in str(error.value)

    def test_a_partial_write_never_appears_at_the_final_path(self, tmp_path: Path):
        """Counter-example (row 4), from the writer's side.

        The store writes to a temporary name and renames into place, so an
        interruption leaves either nothing or a complete snapshot -- never a
        truncated file that hashes to something nobody asked for (R2.8).
        """
        store = SnapshotStore(tmp_path)
        digest = store.put(INC_4821)
        final = tmp_path / SNAPSHOT_ROOT / snapshot_path(digest)

        leftovers = [p for p in final.parent.iterdir() if p != final]

        assert leftovers == [], f"temporary files left beside the snapshot: {leftovers}"
