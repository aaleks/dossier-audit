"""A gold set projected onto MLflow evaluation dataset records (spec 012).

Pure, and deliberately so: what a record holds is a decision, and the call that
sends it is wiring. `infrastructure/tracking/` does the sending.

The projection is one way only. Nothing here reads a dataset back, because a
score, a key or a file computed from one would make a tracking server an input to
a run (R12.4, R10.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dossier.domain.gold import GoldDocument

# The record tag carrying the snapshot address a document's answers were verified
# against. A tag rather than an input: MLflow merges a record onto the SHA-256 of
# its `inputs`, so a snapshot in there would make a repointed document (R2.18) a
# second record beside its own older self instead of an update to it (R12.2).
SNAPSHOT_TAG = "dossier.snapshot"


@dataclass(frozen=True)
class PublishedDataset:
    """What a registry says about a dataset it published or found (spec 012).

    The one thing in `dossier` that comes *back* from a tracking server, which is
    why publishing has a port of its own rather than a method on `Tracker`
    (R0.10). Every field here may reach an MLflow tag and a line in the terminal,
    and none of it may reach a key, a manifest, a score or any file on disk
    (R12.4 row 3).
    """

    dataset_id: str
    name: str
    digest: str
    # How many records the dataset holds now, and how many this publish added.
    # R12.3 is a claim about both: republishing an unchanged gold set leaves the
    # first alone and makes the second zero.
    records: int
    added: int
    created: bool
    tags: Mapping[str, str] = field(default_factory=dict)


def record_for(document: GoldDocument, *, snapshot: str | None = None) -> dict[str, Any]:
    """The one dataset record a verified document projects onto (R12.2).

    `inputs` holds the document key and nothing else: it is the record's
    identity, and everything in it is part of the merge key.
    """
    record: dict[str, Any] = {
        "inputs": {"document": document.document},
        "expectations": {name: answer.get("value") for name, answer in document.fields.items()},
    }
    if snapshot is not None:
        record["tags"] = {SNAPSHOT_TAG: snapshot}
    return record
