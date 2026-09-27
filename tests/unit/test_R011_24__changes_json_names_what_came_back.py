"""R11.24 — a sync's `changes.json` names each item that came back, under `returned`.

R2.25 put a third kind of line under a source, and R11.6's record did not carry
it: a sync that revived an item named it in the terminal and attached two empty
lists. `returned` is a list of `{source, key}`, with `from` and `to` only when
the item came back with other bytes -- the addresses its terminal line prints.

This file proves the record; the acceptance test beside it proves the command
attaches it.
"""

from __future__ import annotations

import json

from dossier.application.sync import SourceReport, changes_artifact
from dossier.domain.sync import Repointed, Returned

BEFORE = "0e52dd18" + "0" * 56
AFTER = "77c1b40a" + "0" * 56


class TestChangesJsonNamesWhatCameBack:
    """R11.24 — `returned` beside `changed` and `tombstoned`."""

    def test_an_item_back_with_its_bytes_is_named_without_addresses(self):
        """Row 1: the one where `audit-note.pdf` was put back as it was."""
        reports = [
            SourceReport(source_id="incidents-manual", returned=(Returned("audit-note.pdf"),))
        ]

        assert json.loads(changes_artifact(reports)) == {
            "changed": [],
            "returned": [{"source": "incidents-manual", "key": "audit-note.pdf"}],
            "tombstoned": [],
        }

    def test_an_item_back_with_other_bytes_carries_both_addresses(self):
        """Row 2: the one where `INC-4821` changed while it was gone; still not `changed`."""
        moved = Repointed("INC-4821", BEFORE, AFTER)
        reports = [
            SourceReport(source_id="incidents-jira", returned=(Returned("INC-4821", moved),))
        ]

        record = json.loads(changes_artifact(reports))

        assert record["returned"] == [
            {"source": "incidents-jira", "key": "INC-4821", "from": BEFORE, "to": AFTER}
        ]
        assert record["changed"] == []

    def test_a_sync_where_nothing_came_back_holds_an_empty_list(self):
        """Counter-example (row 3): the one where `returned` is present and empty."""
        reports = [SourceReport(source_id="incidents-manual", known=3, fetched=3)]

        assert json.loads(changes_artifact(reports))["returned"] == []

    def test_returned_items_are_in_source_order_whatever_order_the_sources_ran_in(self):
        """The one where two sources each revive one; the bytes are the same (R0.4)."""
        jira = SourceReport(source_id="incidents-jira", returned=(Returned("INC-4821"),))
        manual = SourceReport(
            source_id="incidents-manual", returned=(Returned("audit-note.pdf"),)
        )

        assert changes_artifact([manual, jira]) == changes_artifact([jira, manual])
        assert [
            item["source"] for item in json.loads(changes_artifact([manual, jira]))["returned"]
        ] == ["incidents-jira", "incidents-manual"]
