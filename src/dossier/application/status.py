"""The reading half of `dossier status` (spec 017): what the workspace holds.

What to say about it is `dossier.domain.status`'s. Everything here reads, and
nothing writes: `status` promises to change no file (R17.5).
"""

from __future__ import annotations

from pathlib import Path

from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.run import recorded_failures
from dossier.domain.status import RunSeen
from dossier.domain.store import RUNS_ROOT


def read_runs(workspace: Path) -> list[RunSeen]:
    """Every run under `runs/`, with its documents and what it failed (R17.3).

    A run is a directory holding `manifest.json`, as `gc` counts one (R16.2):
    anything else under `runs/` was put there by a person (R0.11), and is not a
    run however its name sorts. A run that stopped wrote no `failures.json`,
    and is read as having recorded none, which is not as having failed none.
    """
    runs = workspace / RUNS_ROOT
    if not runs.is_dir():
        return []
    seen = []
    for directory in sorted(path for path in runs.iterdir() if path.is_dir()):
        manifest = directory / MANIFEST_NAME
        if not manifest.is_file():
            continue
        plan = Manifest.read(manifest).plan
        failures = recorded_failures(directory)
        seen.append(
            RunSeen(
                run_id=directory.name,
                pipeline=plan.pipeline,
                documents=len(plan.documents),
                failed=None
                if failures is None
                else tuple(str(failure["document"]) for failure in failures),
            )
        )
    return seen
