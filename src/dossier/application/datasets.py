"""Publishing a gold set as an MLflow evaluation dataset (spec 012).

The use case `dossier dataset publish` runs. It reads `gold/`, projects each
verified document onto a record (R12.2) and hands the lot to a `DatasetRegistry`
it is given rather than one it builds -- the registry is infrastructure, and which
one this is belongs to the composition root.

Nothing here reads a dataset back into anything. A dataset is written from `gold/`
and read by a person (R12.4).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from dossier.domain.datasets import PublishedDataset, record_for
from dossier.domain.gold import GoldDocument, gold_set_hash
from dossier.domain.ports import DatasetRegistry

GOLD_HASH_TAG = "dossier.gold_hash"
VERIFIED_BY_TAG = "dossier.verified_by"


class EmptyGoldSet(ValueError):
    """The gold directory holds no verified answers, so there is nothing to publish.

    A `ValueError` rather than an empty dataset: a dataset of no records reads in
    the UI as a gold set nobody has filled in yet, which is what the empty
    directory already says -- and a later publish could not tell that dataset from
    one whose answers had been deleted (R12.1 row 3).
    """


def publish_gold(
    registry: DatasetRegistry,
    *,
    gold: Path,
    experiment: str,
    snapshots: Mapping[str, str] | None = None,
) -> PublishedDataset:
    """The gold set at `gold`, published as the dataset named after it (R12.1).

    `snapshots` maps a document key to the snapshot address it is held at, from
    the ledger. A document missing from it publishes without the tag rather than
    being refused: the snapshot is provenance for the answers, not a precondition
    for having them (R12.2 row 3).
    """
    files = {path.name: path.read_bytes() for path in sorted(gold.glob("*.json"))}
    if not files:
        raise EmptyGoldSet(f"{gold}: no verified answers to publish")

    held = snapshots or {}
    documents = _documents(files)
    records = [
        record_for(document, snapshot=held.get(key))
        for key, document in sorted(documents.items())
    ]
    return registry.publish(
        name=gold.name,
        experiment=experiment,
        records=records,
        tags={
            # The same hash an eval tags its own run with (R11.3 row 2), so the
            # dataset and the runs measured against it can be shown to be about
            # the same answers -- which is the whole point of publishing it.
            GOLD_HASH_TAG: gold_set_hash(files),
            VERIFIED_BY_TAG: ", ".join(
                sorted({document.verified_by for document in documents.values()})
            ),
        },
    )


def _documents(files: Mapping[str, bytes]) -> dict[str, GoldDocument]:
    """Every gold file, by the document it verifies.

    Keyed by the `document` inside the file rather than by its name, as
    `load_gold` keys it: the key is what a run reports a document under (R4.10),
    and it is what a record's `inputs` must name for the two to line up.
    """
    documents: dict[str, GoldDocument] = {}
    for name in sorted(files):
        gold = GoldDocument.model_validate(json.loads(files[name].decode("utf-8")))
        documents[gold.document] = gold
    return documents
