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
OUTCOME_NAME = "outcome.json"


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


class DocumentFailure(BaseModel):
    """One (step, document) a run produced no usable output for (R4.13)."""

    model_config = ConfigDict(frozen=True)

    step: str
    document: str
    # What the stage said when it gave up. Carried so a person reading the run
    # back a month later does not have to find the terminal it scrolled off.
    error: str = ""


class Outcome(BaseModel):
    """What a finished run could not produce -- `runs/<run_id>/outcome.json` (R4.13).

    Separate from the manifest, and that is the whole design. The manifest is
    written before the first stage runs, so a run interrupted halfway has one
    (R4.1); writing failures into it at the end would mean an interrupted run
    left a manifest claiming nothing failed, which is worse than no claim at all.

    This file is written when the run reaches the end, so its **absence is
    meaningful**: nothing is known about what that run produced, and a replay
    refuses a missing entry by key as it always did (R4.7). Every run recorded
    before this rule existed reads that way too, which is what makes the change
    safe on a workspace full of old runs.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    failed: tuple[DocumentFailure, ...] = ()

    @property
    def failed_documents(self) -> frozenset[str]:
        """The document keys this run produced nothing for, whatever the step.

        A set, because every caller asks "was this one produced?" -- a replay
        deciding whether to look for an artifact, and a comparison deciding
        which documents were really scored (R7.8).
        """
        return frozenset(failure.document for failure in self.failed)

    def write(self, runs: Path) -> Path:
        """Write `runs/<run_id>/outcome.json` and return its path.

        No clock and no duration: this layer takes its time as an argument and
        has none to take here. The file says what the run could not produce, and
        `manifest.json` beside it says when the run started.
        """
        path = runs / self.run_id / OUTCOME_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def read(cls, directory: Path) -> Outcome | None:
        """The outcome beside a run's manifest, or `None` when the run left none.

        `None` rather than an empty `Outcome`: a run that recorded nothing is not
        a run that recorded no failures, and collapsing the two would let a
        replay treat an interrupted run's missing artifacts as deliberate.
        """
        path = directory / OUTCOME_NAME
        try:
            return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (FileNotFoundError, ValueError):
            # Unreadable is unknown, for the same reason absent is: the safe
            # answer is the one that refuses rather than the one that assumes.
            return None
