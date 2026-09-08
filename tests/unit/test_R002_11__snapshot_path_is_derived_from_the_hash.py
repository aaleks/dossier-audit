"""R2.11 — a snapshot's path is derived from its content hash alone.

`.dossier/snapshots/<first two>/<next two>/<full hash>`. Nothing else enters the
path: not the source id, not the item key, not the fetch time.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.hashing import content_hash
from dossier.domain.store import SNAPSHOT_ROOT, snapshot_path

# The worked example from specs/_fixtures.md. A real digest, not the 8-character
# display prefix the specs write for readability.
INC_4821 = content_hash(b"# INC-4821\n\ntotal exposure CHF 48'200\n")


class TestSnapshotPath:
    """R2.11 — the path is a pure function of the content."""

    def test_the_path_shards_two_levels_and_keeps_the_full_digest(self):
        """The one where a digest becomes a place on disk.

        Example 1. Sharded so that a source with tens of thousands of items does
        not produce one enormous directory.
        """
        assert snapshot_path(INC_4821) == f"{INC_4821[:2]}/{INC_4821[2:4]}/{INC_4821}"

    def test_the_filename_is_the_whole_digest(self):
        """The one where the name on disk is verifiable, not abbreviated."""
        assert snapshot_path(INC_4821).rsplit("/", 1)[-1] == INC_4821
        assert len(snapshot_path(INC_4821).rsplit("/", 1)[-1]) == 64

    def test_the_shard_is_taken_from_the_digest_itself(self):
        """The one where computing the path needs nothing but the hash.

        No lookup, no counter, no directory listing -- which is what lets the
        store be read by a replay that has no ledger to consult (R4.7).
        """
        digest = content_hash(b"anything at all")

        assert snapshot_path(digest).startswith(f"{digest[:2]}/{digest[2:4]}/")

    def test_identical_bytes_from_two_sources_land_in_one_place(self):
        """The one where content addressing deduplicates.

        Example 2: the same attachment on a Jira issue and in the manual folder
        is one snapshot, referenced twice (R1.6 example 3). The function takes
        only a digest, so there is nowhere for a source id to enter.
        """
        payload = b"identical attachment bytes"

        from_jira = snapshot_path(content_hash(payload))
        from_folder = snapshot_path(content_hash(payload))

        assert from_jira == from_folder

    def test_the_same_bytes_a_year_apart_give_the_same_path(self):
        """Example 3: the one where time is not part of the address."""
        assert snapshot_path(INC_4821) == snapshot_path(INC_4821)

    def test_two_items_sharing_a_key_in_different_sources_do_not_collide(self):
        """Counter-example (row 4): the one where the key is irrelevant here.

        `INC-4821` could exist in two sources with different content. The store
        separates them because their bytes differ; the ledger separates them by
        `source_id`. Neither mechanism needs the other.
        """
        one = snapshot_path(content_hash(b"INC-4821 as held by jira"))
        other = snapshot_path(content_hash(b"INC-4821 as dropped in the folder"))

        assert one != other

    def test_the_path_is_posix_regardless_of_platform(self):
        """The one where a Windows separator would break a cache key.

        R5.6 requires paths to enter keys with forward slashes, so the domain
        never produces an OS-specific separator. This is also why the function
        returns a str: `domain/` may not import `pathlib` at all.
        """
        path = snapshot_path(INC_4821)

        assert "\\" not in path
        assert path.count("/") == 2

    def test_the_store_root_is_named_once(self):
        """The one where `.dossier/snapshots` is not spelled out per call site."""
        assert SNAPSHOT_ROOT == ".dossier/snapshots"

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("a3f9c1e2", id="display-prefix"),
            pytest.param("20260806T142203Z-4f1a", id="run-id"),
            pytest.param("", id="empty"),
        ],
    )
    def test_only_a_real_digest_can_become_a_path(self, value: str):
        """The one where a short hash does not silently become a short path.

        `a3f9c1e2` would shard to `a3/f9/a3f9c1e2` and look entirely plausible.
        """
        with pytest.raises(ValueError):
            snapshot_path(value)
