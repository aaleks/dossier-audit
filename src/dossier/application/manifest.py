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
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def read(cls, path: Path) -> Manifest:
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
