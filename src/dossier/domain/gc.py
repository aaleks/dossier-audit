"""What `dossier gc` keeps, and what it deletes (spec 016).

Pure decisions over what is held. Which runs are held, and which cache keys a
kept run's replay reads, are found by the application; what to keep of them is
decided here, where it is provable without a workspace.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

# How many runs of each pipeline are kept when `--keep-last` does not say
# (decided by `a.aleks` on 2026-09-30, R16.2).
KEEP_LAST = 5
# A run whose directory holds this file is kept by every `gc` (R16.2, R16.6). On
# disk rather than a `--label`: the label lives only in MLflow (R10.11), and `gc`
# reads nothing back from there (R0.10).
KEEP_FILE = "keep"


@dataclass(frozen=True)
class HeldRun:
    """A run under `runs/`: its id, the pipeline its manifest names, and its pin."""

    run_id: str
    pipeline: str
    pinned: bool = False


def kept_runs(
    runs: Iterable[HeldRun], *, keep_last: int = KEEP_LAST
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The runs kept and the runs deleted, each by run id in run-id order (R16.2).

    The latest `keep_last` of each pipeline are kept, and every pinned run. The
    latest are the last by run id, which sorts by the time the run started
    (R0.8), as `dossier eval` finds the latest run -- so `gc` and `eval` never
    disagree about which run is the latest. Counted per pipeline: one pipeline
    run nightly must not push another's only runs out.
    """
    by_pipeline: dict[str, list[HeldRun]] = {}
    for run in sorted(runs, key=lambda held: held.run_id):
        by_pipeline.setdefault(run.pipeline, []).append(run)
    kept: set[str] = set()
    for held in by_pipeline.values():
        # From zero at the least: fewer runs than `keep_last` keeps them all, and a
        # negative start would slice from the end and keep only the last few.
        latest = held[max(0, len(held) - keep_last) :] if keep_last > 0 else []
        kept.update(run.run_id for run in latest)
        kept.update(run.run_id for run in held if run.pinned)
    every = sorted(run.run_id for held in by_pipeline.values() for run in held)
    return (
        tuple(run for run in every if run in kept),
        tuple(run for run in every if run not in kept),
    )


# The caches `gc` collects from (R16.3). Not the judge's: no manifest names a
# verdict, and a judge asked again can move a kept run's score (R7.18).
STAGE = "stage"
CONVERT = "convert"
COLLECTED_CACHES = (STAGE, CONVERT)


@dataclass(frozen=True)
class CacheEntry:
    """One cache entry: its cache, its key, and for a conversion, its snapshot."""

    namespace: str
    key: str
    snapshot: str | None = None


def collectable(
    entries: Iterable[CacheEntry],
    *,
    needed: Mapping[str, Collection[str]],
    held: Collection[str],
) -> tuple[CacheEntry, ...]:
    """The entries `gc` deletes, by cache and key (R16.3).

    `needed` is what the replays of the kept runs read, by cache: what a kept
    run is reproduced from, whichever run first wrote it. `held` is the
    snapshots the ledger holds now, whose conversions the next run reads, and
    re-converting a scanned PDF takes minutes. Anything else nothing will read
    without computing it again.
    """
    return tuple(
        sorted(
            (
                entry
                for entry in entries
                if entry.key not in needed.get(entry.namespace, ())
                and not (entry.namespace == CONVERT and entry.snapshot in held)
            ),
            key=lambda entry: (entry.namespace, entry.key),
        )
    )
