"""`dossier gc`: reclaiming space without making a kept run irreproducible (spec 016).

The reads are here -- which runs `runs/` holds, what their replays read -- and
the decisions are `dossier.domain.gc`'s. The stores are handed in, as they are
to a replay: this module constructs none of them.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.run import (
    MissingFromReplay,
    recorded_failures,
    replay,
    replayed_inputs,
    replayed_parts,
)
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
from dossier.domain.ports import ArtifactStore, CollectableStore, SnapshotReader, Tracker
from dossier.domain.resolution import is_run_id
from dossier.domain.store import FAILURES_NAME, REPLAYS, RUNS_ROOT, TRIES_ROOT
from dossier.domain.tracking import gc_description, label_for, run_name
from dossier.domain.tracking import tags as tracking_tags


@dataclass(frozen=True)
class GcPlan:
    """What `dossier gc` deletes (R16.2 - R16.4).

    The runs not kept, the entries nothing kept reads, every try, and the
    replays under the runs kept, as paths relative to the workspace. A replay
    under a run that is deleted goes with its run, and is not named twice.
    """

    runs: tuple[HeldRun, ...]
    entries: tuple[CacheEntry, ...]
    tries: tuple[str, ...] = ()
    replays: tuple[str, ...] = ()
    # Kept runs whose replay already stops, each with the replay's error (R16.7).
    unreplayable: tuple[tuple[str, str], ...] = ()
    # Those of them that stopped before their stages, so collect nothing (R16.8).
    untraced: tuple[str, ...] = ()
    # Directories under `runs/` whose manifest cannot be read, each with why:
    # left as they are, as one with no manifest is (R16.11).
    unreadable: tuple[tuple[str, str], ...] = ()


def held_runs(runs: Path, *, unreadable: list[tuple[str, str]] | None = None) -> list[HeldRun]:
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
        try:
            pipeline = Manifest.read(manifest).plan.pipeline
        except ValueError as error:
            # Cut short by a run killed as it wrote it: it says nothing of the
            # run, not even its pipeline, so the directory is left as one with
            # no manifest is, and named rather than stopping gc (R16.11).
            if unreadable is not None:
                unreadable.append((directory.name, str(error)))
            continue
        held.append(
            HeldRun(
                run_id=directory.name,
                pipeline=pipeline,
                pinned=(directory / KEEP_FILE).is_file(),
            )
        )
    return held


def gc_plan(
    workspace: Path,
    *,
    store: SnapshotReader,
    caches: Mapping[str, CollectableStore],
    held: Collection[str],
    keep_last: int = KEEP_LAST,
) -> GcPlan:
    """What `gc` deletes, and nothing deleted yet (R16.2 - R16.4).

    `caches` are the stage and convert caches, by name; `held` the snapshots the
    ledger holds now.
    """
    runs = workspace / RUNS_ROOT
    unreadable: list[tuple[str, str]] = []
    every = held_runs(runs, unreadable=unreadable)
    kept, deleted = kept_runs(every, keep_last=keep_last)
    needed, unreplayable, untraced = _needed(runs, kept, store=store, caches=caches)
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
    tries = workspace / TRIES_ROOT
    return GcPlan(
        runs=tuple(run for run in every if run.run_id in set(deleted)),
        entries=collectable(entries, needed=needed, held=held, untraced=untraced),
        unreplayable=unreplayable,
        untraced=untraced,
        unreadable=tuple(unreadable),
        # Every try: none is ever replayed or scored (R4.20), and an answer of
        # one that a run was served is that run's entry (R16.3 row 3).
        tries=tuple(
            f"{TRIES_ROOT}/{path.name}"
            for path in sorted(tries.iterdir() if tries.is_dir() else ())
            if path.is_dir() and is_run_id(path.name)
        ),
        # Every replay under a kept run: byte copies of entries its run
        # reproduces at any time (R0.12, R16.4).
        replays=tuple(
            f"{RUNS_ROOT}/{run}/{REPLAYS}/{path.name}"
            for run in kept
            for path in sorted((runs / run / REPLAYS).glob("*"))
            if path.is_dir() and is_run_id(path.name)
        ),
    )


def _needed(
    runs: Path,
    kept: Collection[str],
    *,
    store: SnapshotReader,
    caches: Mapping[str, CollectableStore],
) -> tuple[dict[str, set[str]], tuple[tuple[str, str], ...], tuple[str, ...]]:
    """The keys each kept run's replay reads, by cache, and the runs that stop (R16.3).

    Found by running that replay, reading through a cache that notes each key
    it is asked for and writes nothing. It is the replay the kept run would get,
    so a key it reads cannot be missed by a second computation of the keys that
    drifted from the first. The copies under `runs/` are never read back
    (R0.11), so they decide nothing.
    """
    traced = {namespace: _Traced(caches[namespace]) for namespace in COLLECTED_CACHES}
    unreplayable: list[tuple[str, str]] = []
    untraced: list[str] = []
    for run_id in kept:
        manifest = Manifest.read(runs / run_id / MANIFEST_NAME)
        try:
            text = replayed_inputs(manifest, store=store, cache=traced[CONVERT])
            parts = replayed_parts(manifest, store=store, cache=traced[CONVERT])
            failures = _failures(runs / run_id)
        except MissingFromReplay as error:
            # Stopped before any stage key was read: a deleted conversion, which
            # `dossier convert` makes again (R5.9), or a record of failures cut
            # short (R16.11). Which answers it needs is unknown, so none may go
            # (R16.8).
            unreplayable.append((run_id, str(error)))
            untraced.append(run_id)
            continue
        try:
            replay(
                manifest=manifest,
                document_text=text,
                document_parts=parts,
                cache=traced[STAGE],
                failures=failures,
            )
        except MissingFromReplay as error:
            # Already irreproducible, so `gc` cannot make it so: named, and
            # what its replay read before it stopped is kept, as traced
            # (R16.7). Stopping here would let one killed run block every gc.
            unreplayable.append((run_id, str(error)))
    return (
        {namespace: cache.read for namespace, cache in traced.items()},
        tuple(unreplayable),
        tuple(untraced),
    )


def _failures(run_dir: Path):
    """What the run recorded as failed, or `MissingFromReplay` naming a record cut short.

    `failures.json` is written once the run ends, not all at once, so a run
    killed as it wrote it leaves it unreadable. Its replay cannot start, which
    is R16.8's case: named, and nothing collected (R16.11).
    """
    try:
        return recorded_failures(run_dir)
    except ValueError as error:
        raise MissingFromReplay(f"{FAILURES_NAME} cannot be read: {error}") from error


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


def _directories(workspace: Path, plan: GcPlan) -> list[Path]:
    """The directories `plan` deletes whole: runs, tries and replays."""
    return [
        *(workspace / RUNS_ROOT / run.run_id for run in plan.runs),
        *(workspace / path for path in plan.tries),
        *(workspace / path for path in plan.replays),
    ]


def plan_size(workspace: Path, plan: GcPlan, *, caches: Mapping[str, CollectableStore]) -> int:
    """The bytes every file `plan` deletes takes, for the line `gc` prints (R16.5)."""
    files = sum(
        path.stat().st_size
        for directory in _directories(workspace, plan)
        for path in directory.rglob("*")
        if path.is_file()
    )
    return files + sum(caches[entry.namespace].size(entry.key) for entry in plan.entries)


def apply_plan(
    workspace: Path, plan: GcPlan, *, caches: Mapping[str, CollectableStore]
) -> None:
    """Delete what `plan` names, and nothing else (R16.2 - R16.4).

    Directories first, then cache entries. Interrupted between the two, what
    is left is entries no run names, which the next `gc` collects; the other
    order could leave a run directory whose entries are gone, a run that no
    longer replays.
    """
    for directory in _directories(workspace, plan):
        _delete_tree(directory)
    for entry in plan.entries:
        caches[entry.namespace].delete(entry.key)


def _delete_tree(directory: Path) -> None:
    """Delete `directory` and all it holds, its `manifest.json` last (R16.10).

    A directory under `runs/` is a run while it holds its manifest (R16.2).
    Deleted in the order the file system lists it, a `gc` stopped part way
    could leave the rest with no manifest, which no later `gc` counts as a run
    or deletes. Manifest last, it stays a run until it is gone, and the next
    `gc` finishes what this one began. Deepest first, so each directory is
    empty when it is removed.
    """
    manifest = directory / MANIFEST_NAME
    for path in sorted(directory.rglob("*"), key=lambda held: len(held.parts), reverse=True):
        if path == manifest:
            continue
        if path.is_dir() and not path.is_symlink():
            path.rmdir()
        else:
            path.unlink()
    manifest.unlink(missing_ok=True)
    directory.rmdir()


def pin_runs(workspace: Path, run_ids: Collection[str]) -> None:
    """Pin each run by writing `runs/<run_id>/keep` (R16.6).

    Every run is checked before any pin is written, so a mistyped id refuses
    the whole command rather than pinning half of what was asked. Raises
    `ValueError` naming the first run that is not there.
    """
    runs = workspace / RUNS_ROOT
    for run_id in run_ids:
        manifest = runs / run_id / MANIFEST_NAME
        if not manifest.is_file():
            raise ValueError(
                f"no run {run_id} -- expected {RUNS_ROOT}/{run_id}/{MANIFEST_NAME}"
            )
    for run_id in run_ids:
        (runs / run_id / KEEP_FILE).write_text("", encoding="utf-8")


# Beside a `gc --apply`'s record: each run it deleted, and its pipeline (R11.28).
COLLECTED_NAME = "collected.json"


def record_gc(
    tracker: Tracker,
    *,
    experiment: str,
    plan: GcPlan,
    size: int,
    keep_last: int,
    lines: Sequence[str],
    started: str,
    environ: Mapping[str, str],
    dossier_version: str,
    label: str = "",
) -> None:
    """Record a `gc --apply` as one MLflow run of what it deleted (R11.28).

    Opened once the deleting is done, as a comparison opens once both sides
    are scored: what it records are the counts the line printed, and they do
    not exist before. `collected.json` names each run deleted, so a run whose
    record is still in MLflow can be traced to the `gc` that removed its files.
    No traces: `gc` asks no model.
    """
    label = label_for(label, environ)
    tracker.start_run(
        experiment=experiment,
        name=run_name(kind="gc", values={"started": started, "label": label}, environ=environ),
        # `dossier.pipeline` present and empty, as `dossier.label` is when
        # nobody gave one: `gc` reclaims space across every pipeline.
        tags=tracking_tags(kind="gc", pipeline="", label=label, environ=environ),
    )
    params = {"keep_last": str(keep_last)}
    if dossier_version:
        # Which dossier did the deleting (R11.19).
        params["dossier_version"] = dossier_version
    tracker.log_params(params)
    tracker.log_metrics(
        {
            "runs": len(plan.runs),
            "tries": len(plan.tries),
            "replays": len(plan.replays),
            "entries": len(plan.entries),
            # The figure the line printed, not a second computation of it.
            "megabytes": round(size / 1_000_000, 1),
        }
    )
    collected = [{"run": run.run_id, "pipeline": run.pipeline} for run in plan.runs]
    written = json.dumps(collected, indent=2) + "\n"
    tracker.log_artifact(COLLECTED_NAME, written.encode("utf-8"))
    tracker.describe(gc_description(lines=lines))
    tracker.end_run(status="FINISHED")
