"""R012.3 — republishing an unchanged gold set adds no record and leaves the digest unchanged.

Publishing is something a person does by hand after a review, so it has to be safe
to do twice. The claim is about counts: how many datasets were created, how many
records were added, and whether the digest moved.

The gold set is the person-written one in `tests/fixtures/gold/incidents/`, copied
into a `workspace` — four documents, four records.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import FakeDatasetRegistry

EXPERIMENT = "dossier-audit/incident-audit/eval/incidents"


def _publish(registry: FakeDatasetRegistry, gold: Path, **kwargs):
    from dossier.application.datasets import publish_gold

    return publish_gold(registry, gold=gold, experiment=EXPERIMENT, **kwargs)


class TestRepublishingAnUnchangedGoldSetChangesNothing:
    """R12.3 — republishing an unchanged gold set adds no record, and no digest moves."""

    def test_publishing_twice_is_publishing_once(self, workspace: Path):
        """Example 1: the one where nothing changed, so nothing should happen.

        The second publish creates no dataset, adds no record and leaves the
        digest where it was. Records merge on the document their `inputs` name, so
        the same four documents merge onto the same four records.
        """
        registry = FakeDatasetRegistry()
        gold = workspace / "gold" / "incidents"

        first = _publish(registry, gold)
        second = _publish(registry, gold)

        assert first.records == 4
        assert first.added == 4, "the first publish adds all four"
        assert second.records == 4, "still four records, not eight"
        assert second.added == 0, "the second adds nothing"
        assert second.digest == first.digest
        assert registry.created == ["incidents"], "one dataset, created once"

    def test_a_corrected_answer_moves_the_digest_without_adding_a_record(self, workspace: Path):
        """Example 2: the one where a reviewer changed an answer.

        The document is the merge key, not the answer — so a correction updates
        the record a person already has. The digest moves, because what the
        dataset says has changed.
        """
        registry = FakeDatasetRegistry()
        gold = workspace / "gold" / "incidents"
        first = _publish(registry, gold)

        path = gold / "INC-4822.json"
        corrected = json.loads(path.read_text(encoding="utf-8"))
        corrected["fields"]["resolution_date"] = {"value": "2026-07-30"}
        path.write_text(
            json.dumps(corrected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        second = _publish(registry, gold)

        assert second.records == 4, "a correction is not a fifth document"
        assert second.added == 0
        assert second.digest != first.digest, "what the dataset says has changed"

    def test_a_newly_verified_document_is_a_new_record(self, workspace: Path):
        """Example 3: the one where the gold set grew.

        The four already there are untouched, which is what makes publishing an
        addition rather than a replacement.
        """
        registry = FakeDatasetRegistry()
        gold = workspace / "gold" / "incidents"
        first = _publish(registry, gold)

        (gold / "INC-4830.json").write_text(
            json.dumps(
                {
                    "document": "INC-4830",
                    "verified_by": "a.aleks",
                    "verified_at": "2026-09-15",
                    "fields": {"severity": {"value": "major"}},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        second = _publish(registry, gold)

        assert second.records == 5
        assert second.added == 1
        assert second.digest != first.digest

    def test_a_repointed_document_updates_its_snapshot_tag_in_place(self, workspace: Path):
        """Example 4: the one where a sync repointed a document (R2.18).

        The case the merge key is chosen for. A record keyed on its snapshot as
        well would leave `INC-4822` holding two records, one of them addressing
        content the store no longer serves.
        """
        registry = FakeDatasetRegistry()
        gold = workspace / "gold" / "incidents"
        before = {"INC-4822": "0e52dd18" * 8}
        after = {"INC-4822": "77c1b40a" * 8}

        _publish(registry, gold, snapshots=before)
        second = _publish(registry, gold, snapshots=after)

        assert second.records == 4, "one document, one record, whatever it is held at"
        assert second.added == 0
        held = [
            record
            for record in registry.datasets["incidents"].records.values()
            if record["inputs"]["document"] == "INC-4822"
        ]
        assert len(held) == 1
        assert held[0]["tags"]["dossier.snapshot"] == after["INC-4822"]

    def test_a_gold_file_rewritten_byte_for_byte_differently_moves_the_digest(
        self, workspace: Path
    ):
        """Counter-example (row 5): the one where only the formatting changed.

        The gold set hash is over bytes (R0.7), so the set this dataset claims to
        address has moved even though every answer is the same. A digest that
        ignored the rewrite would claim a set nobody can reproduce.
        """
        registry = FakeDatasetRegistry()
        gold = workspace / "gold" / "incidents"
        first = _publish(registry, gold)

        path = gold / "INC-4901.json"
        same_answers = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(same_answers, indent=4, sort_keys=True), encoding="utf-8")

        second = _publish(registry, gold)

        assert second.records == 4
        assert second.added == 0
        assert second.tags["dossier.gold_hash"] != first.tags["dossier.gold_hash"], (
            "the set it addresses has moved"
        )
