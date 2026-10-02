"""The frozen description of one run (spec 004).

`runs/<run_id>/manifest.json`, written before the first stage executes. A run
that was interrupted halfway still has one, which is the point: an interrupted
run is the normal case rather than the exotic one, and a run with no manifest
cannot be replayed (R4.7).

The format lives here rather than in whatever happens to write it first, so that
`--plan` reading a past run and `run` writing this one cannot drift into two
shapes of the same file.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from dossier.domain.resolution import ResolvedPlan

MANIFEST_NAME = "manifest.json"


class Manifest(BaseModel):
    """A resolved plan, plus the three things that say which run it was.

    The split is exact and load-bearing: everything in `plan` is what the run
    read and did, and is byte-identical between two resolutions of the same
    pipeline (R4.8); everything beside it records *when*, and is expected to
    differ. Keeping them in separate fields is what lets a comparison be written
    without a list of exclusions that someone has to remember to update.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    started_at: datetime
    dossier_version: str
    plan: ResolvedPlan

    def write(self, runs: Path) -> Path:
        """Write `runs/<run_id>/manifest.json` and return its path.

        `indent=2` because a person opens this file -- `runs/` is not hidden, by
        deliberate choice (R0.8) -- and a one-line manifest would make a diff
        between two runs unreadable, which is most of what anyone wants from it.
        """
        directory = runs / self.run_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / MANIFEST_NAME
        write_whole(path, self.model_dump_json(indent=2))
        return path

    @classmethod
    def read(cls, path: Path) -> Manifest:
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


# The rename that makes a write whole, named so a test can stop a write before it.
_rename = os.replace


def write_whole(path: Path, text: str, *, newline: str | None = None) -> None:
    """Write `text` to `path` whole, or leave `path` as it was (R4.29).

    Written beside it under a temporary name, then renamed over it. A rename is
    all or nothing, so whoever reads `path` finds the whole file or none, never
    the half a process killed while writing it left (R16.11). `newline` is the
    writer's own, so a file reads as it always did.
    """
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline=newline)
    _rename(temporary, path)


def read_manifest(path: Path) -> Manifest | str:
    """The manifest at `path`, or why it cannot be read, on one line (R4.30).

    Cut short, or edited by a person into something that is not one (R0.11), a
    manifest says nothing of its run, not even its pipeline. So the caller
    passes it over and names it, as `gc` does (R16.11), and goes on.
    """
    try:
        return Manifest.read(path)
    except ValueError as error:
        return " ".join(str(error).split())
