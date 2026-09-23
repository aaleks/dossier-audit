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
from dossier.domain.hashing import content_hash
from dossier.domain.ports import DatasetRegistry
from dossier.domain.tracking import namespaced

GOLD_HASH_TAG = "dossier.gold_hash"
VERIFIED_BY_TAG = "dossier.verified_by"
# Over the document keys and the snapshot addresses they are held at. Beside the
# gold hash because a sync repointing a document (R2.18) changes what a record's
# snapshot tag should say while leaving every gold file untouched, and a publish
# that compared only the answers would skip it (R12.3 row 4).
SNAPSHOTS_TAG = "dossier.snapshots_hash"


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
    namespace: str = "",
) -> PublishedDataset:
    """The gold set at `gold`, published as the dataset named after it (R12.1).

    `namespace` goes in front of that name (R10.13): a dataset name is global on
    a server, and two workspaces each holding `gold/incidents` would otherwise
    merge their records into one dataset.

    `snapshots` maps a document key to the snapshot address it is held at, from
    the ledger. A document missing from it publishes without the tag rather than
    being refused: the snapshot is provenance for the answers, not a precondition
    for having them (R12.2 row 3).
    """
    files = {path.name: path.read_bytes() for path in sorted(gold.glob("*.json"))}
    if not files:
        raise EmptyGoldSet(f"{gold}: no verified answers to publish")

    name = namespaced(gold.name, namespace)
    held = snapshots or {}
    documents = _documents(files)
    # The same hash an eval tags its own run with (R11.3 row 2), so the dataset and
    # the runs measured against it can be shown to be about the same answers --
    # which is the whole point of publishing it.
    gold_hash = gold_set_hash(files)
    addresses = content_hash(
        "".join(f"{key}\0{held.get(key, '')}\n" for key in sorted(documents)).encode("utf-8")
    )
    tags = {
        GOLD_HASH_TAG: gold_hash,
        SNAPSHOTS_TAG: addresses,
        VERIFIED_BY_TAG: ", ".join(
            sorted({document.verified_by for document in documents.values()})
        ),
    }
    records = (
        []
        if _already_published(registry, name=name, tags=tags)
        else [
            record_for(document, snapshot=held.get(key))
            for key, document in sorted(documents.items())
        ]
    )
    return registry.publish(name=name, experiment=experiment, records=records, tags=tags)


def _already_published(
    registry: DatasetRegistry, *, name: str, tags: Mapping[str, str]
) -> bool:
    """Whether the dataset already holds exactly what this publish would write (R12.3).

    Asked so that an unchanged gold set can be published without sending anything.
    MLflow's digest is over the dataset's name and the time it was last written, not
    over its records, so merging the same records again moves it and offers a person
    two identical versions to compare.

    Both hashes are compared, not just the answers: a repoint (R2.18) changes a
    record's snapshot tag while leaving every gold file alone (R12.3 row 4).

    A registry that cannot answer is treated as not having it. Sending records that
    turn out to be redundant costs a digest; skipping records that were needed would
    leave the dataset quietly wrong, and those are not the same mistake.
    """
    try:
        published = registry.find(name)
    except Exception:
        return False
    if published is None:
        return False
    return all(
        published.tags.get(key) == value
        for key, value in tags.items()
        if key in (GOLD_HASH_TAG, SNAPSHOTS_TAG)
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
