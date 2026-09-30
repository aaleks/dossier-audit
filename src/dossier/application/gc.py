"""`dossier gc`: reclaiming space without making a kept run irreproducible (spec 016).

The reads are here -- which runs `runs/` holds, what their replays read -- and
the decisions are `dossier.domain.gc`'s.
"""

from __future__ import annotations

from pathlib import Path

from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.domain.gc import KEEP_FILE, HeldRun


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
