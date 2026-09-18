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

# How an aggregate step's single artifact is filed (spec 003). Reserved in
# `domain` rather than `application`, because "which keys may a source hold" is
# a decision and the three places that care -- sync, which refuses it in a
# source; run, which files under it; and `output_path` below, which names the
# file -- must not disagree.
RESERVED_KEY = "*"

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


def held_address(path: str) -> str:
    """The content hash a snapshot path was built from: its last segment.

    The inverse of `snapshot_path`, which puts the full digest in the filename
    precisely so that this needs no lookup (R2.11). It is what a sync prints
    when a row is repointed (R2.18): the row's `snapshot_path` is the address a
    person can open, and its `content_hash` is not (R2.17).
    """
    digest = path.rsplit("/", 1)[-1]
    if not is_content_hash(digest):
        raise ValueError(
            f"{path!r} does not end in a content hash, so it is not a snapshot path. "
            "Expected 64 lowercase hex characters as the filename (R0.7, R2.11)."
        )
    return digest


# Relative to the workspace root, like SNAPSHOT_ROOT. Where a run's manifest and
# the copies of its artifacts a person opens are kept (R0.8, R0.11).
RUNS_ROOT = "runs"


def output_path(step: str, document: str, *, structured: bool) -> str:
    """The run-relative path of a step's artifact for a document (R0.11).

    `extract/INC-4821.json`, and for the folder key `PLAY-1001.md`,
    `extract/PLAY-1001.md.json`: the key with the extension appended, never a
    suffix replaced. Replacing it would collide `PLAY-1001.md` with
    `PLAY-1001.pdf`, which R4.10 says are two documents and a run must keep
    apart.

    A step with no `output` declaration returns text rather than a field
    record, and its file carries `.md`: what a person opens is what the model
    wrote, not a JSON string holding it.

    An aggregate step's one artifact is filed under the reserved key `*` (spec
    003), which is not a file name on every platform -- and the step read every
    document, so its file is named for what it is rather than after any one.
    """
    name = "aggregate" if document == RESERVED_KEY else document
    return f"{step}/{name}.{'json' if structured else 'md'}"


def record_path(path: str) -> str:
    """The sibling `<name>.meta.json` for an artifact at `path` (R0.3).

    `extract/INC-4821.json` -> `extract/INC-4821.meta.json`, the last extension
    replaced, which is how the cache names its own records -- so the pair under
    `runs/` looks exactly like the pair under `.dossier/cache/`.
    """
    stem = path.rsplit(".", 1)[0]
    return f"{stem}.meta.json"
