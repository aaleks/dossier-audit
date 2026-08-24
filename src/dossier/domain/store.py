"""Where a snapshot lives, as a pure function of what it contains (R2.11).

The address of a snapshot is derived from its content hash and nothing else --
not the source it came from, not the item key, not when it was fetched. Two
sources holding identical bytes therefore hold one snapshot between them, and a
replay can find what it needs from a manifest alone, with no ledger to consult
(R4.7).

Paths are returned as `str` with forward slashes, not `pathlib.Path`. `domain/`
may not import `pathlib` -- it does no IO -- and R5.6 requires that any path
entering a cache key does so in one platform-independent form. Joining this onto
a real directory is `dossier.infrastructure.store`'s job.
"""

from __future__ import annotations

from dossier.domain.hashing import is_content_hash

# Relative to the workspace root (R0.8). Named once so that no call site spells
# it out and no test asserts a literal it invented.
SNAPSHOT_ROOT = ".dossier/snapshots"

# Two levels of two characters. One flat directory holding a source's worth of
# snapshots degrades on several filesystems well before the volumes described in
# the design deck; two levels keeps any single directory small.
_SHARD_WIDTH = 2
_SHARD_DEPTH = 2


def snapshot_path(digest: str) -> str:
    """The store-relative path for content hashing to `digest`.

    `a3f9c1e2…` -> `a3/f9/a3f9c1e2…`, with the full digest as the filename so a
    snapshot on disk can still be verified against its own name.
    """
    if not is_content_hash(digest):
        # A display prefix would shard to `a3/f9/a3f9c1e2` and look entirely
        # plausible, which is the failure worth refusing: a plausible wrong path
        # is discovered as a cache miss months later, not as an error now.
        raise ValueError(
            f"{digest!r} is not a content hash, so it has no snapshot path. "
            "Expected 64 lowercase hex characters (R0.7)."
        )
    shards = [
        digest[index * _SHARD_WIDTH : (index + 1) * _SHARD_WIDTH]
        for index in range(_SHARD_DEPTH)
    ]
    return "/".join([*shards, digest])
