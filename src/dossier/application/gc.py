"""`dossier gc`: reclaiming space without making a kept run irreproducible (spec 016).

The reads are here -- which runs `runs/` holds, what their replays read -- and
the decisions are `dossier.domain.gc`'s. The stores are handed in, as they are
to a replay: this module constructs none of them.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.run import recorded_failures, replay, replayed_inputs, replayed_parts
from dossier.domain.gc import (
    COLLECTED_CACHES,
    CONVERT,
    KEEP_FILE,
    KEEP_LAST,
    STAGE,
    CacheEntry,
    HeldRun,
    collectable,
    kept_runs,
)
from dossier.domain.ports import ArtifactStore, CollectableStore, SnapshotReader


@dataclass(frozen=True)
class GcPlan:
    """What `dossier gc` deletes: the runs not kept, and the entries nothing kept reads."""

    runs: tuple[HeldRun, ...]
    entries: tuple[CacheEntry, ...]


def held_runs(runs: Path) -> list[HeldRun]:
    """Every run under `runs`, in run-id order (R16.2).

    A run is a directory holding `manifest.json`. Anything else there is not
    one, and is neither kept nor deleted: `runs/` is edited by people (R0.11),
    and `gc` leaves what it cannot account for.
    """
    if not runs.is_dir():
        return []
    held = []
    for directory in sorted(path for path in runs.iterdir() if path.is_dir()):
        manifest = directory / MANIFEST_NAME
        if not manifest.is_file():
            continue
        held.append(
            HeldRun(
                run_id=directory.name,
                pipeline=Manifest.read(manifest).plan.pipeline,
                pinned=(directory / KEEP_FILE).is_file(),
            )
        )
    return held


def gc_plan(
    *,
    runs: Path,
    store: SnapshotReader,
    caches: Mapping[str, CollectableStore],
    held: Collection[str],
    keep_last: int = KEEP_LAST,
) -> GcPlan:
    """What `gc` deletes, and nothing deleted yet (R16.2, R16.3).

    `caches` are the stage and convert caches, by name; `held` the snapshots the
    ledger holds now.
    """
    every = held_runs(runs)
    kept, deleted = kept_runs(every, keep_last=keep_last)
    needed = _needed(runs, kept, store=store, caches=caches)
    entries = [
        CacheEntry(
            namespace=namespace,
            key=key,
            snapshot=(caches[namespace].record(key) or {}).get("snapshot")
            if namespace == CONVERT
            else None,
        )
        for namespace in COLLECTED_CACHES
        for key in caches[namespace].all_keys()
    ]
    return GcPlan(
        runs=tuple(run for run in every if run.run_id in set(deleted)),
        entries=collectable(entries, needed=needed, held=held),
    )


def _needed(
    runs: Path,
    kept: Collection[str],
    *,
    store: SnapshotReader,
    caches: Mapping[str, CollectableStore],
) -> dict[str, set[str]]:
    """The keys each kept run's replay reads, by cache (R16.3).

    Found by running that replay, reading through a cache that notes each key
    it is asked for and writes nothing. It is the replay the kept run would get,
    so a key it reads cannot be missed by a second computation of the keys that
    drifted from the first. The copies under `runs/` are never read back
    (R0.11), so they decide nothing.
    """
    traced = {namespace: _Traced(caches[namespace]) for namespace in COLLECTED_CACHES}
    for run_id in kept:
        manifest = Manifest.read(runs / run_id / MANIFEST_NAME)
        replay(
            manifest=manifest,
            document_text=replayed_inputs(manifest, store=store, cache=traced[CONVERT]),
            document_parts=replayed_parts(manifest, store=store, cache=traced[CONVERT]),
            cache=traced[STAGE],
            failures=recorded_failures(runs / run_id),
        )
    return {namespace: cache.read for namespace, cache in traced.items()}


class _Traced:
    """A cache that notes every key it is asked for, and refuses to be written to."""

    def __init__(self, cache: ArtifactStore) -> None:
        self._cache = cache
        self.read: set[str] = set()

    def get(self, key: str, *, require_record: bool = False) -> bytes | None:
        self.read.add(key)
        return self._cache.get(key, require_record=require_record)

    def record(self, key: str) -> dict | None:
        self.read.add(key)
        return self._cache.record(key)

    def put(self, key: str, payload: bytes, *, record: dict | None = None) -> None:
        raise AssertionError(f"gc wrote to the cache, at {key}: it only ever reads")
