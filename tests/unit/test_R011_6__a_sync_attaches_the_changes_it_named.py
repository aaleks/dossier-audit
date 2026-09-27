"""R11.6 — a `dossier sync` attaches `changes.json`, naming what the terminal named.

The items R2.18 and R2.20 print, as one artifact: `changed` as a list of
`{source, key, from, to}` and `tombstoned` as a list of `{source, key}`. It is
composed from the report's own lists -- the ones the terminal printed -- never
from a second reading of the ledger, so the two cannot disagree (spec 011's
opening principle).

This file proves the record itself; the acceptance test beside it proves the
command attaches it.
"""

from __future__ import annotations

import json

from dossier.application.sync import SourceReport, changes_artifact
from dossier.domain.sync import Repointed

BEFORE = "0e52dd18" + "0" * 56
AFTER = "77c1b40a" + "0" * 56


class TestASyncAttachesTheChangesItNamed:
    """R11.6 — a sync attaches `changes.json`, naming what the terminal named."""

    def test_a_repoint_and_a_tombstone_are_both_in_the_record(self):
        """Example 1: the one where `INC-4822` moved and `INC-4821` left, full hashes."""
        reports = [
            SourceReport(
                source_id="incidents-jira",
                repointed=(Repointed("INC-4822", BEFORE, AFTER),),
                departed=("INC-4821",),
            ),
            SourceReport(source_id="incidents-manual"),
        ]

        assert json.loads(changes_artifact(reports)) == {
            "changed": [
                {"source": "incidents-jira", "key": "INC-4822", "from": BEFORE, "to": AFTER}
            ],
            "returned": [],
            "tombstoned": [{"source": "incidents-jira", "key": "INC-4821"}],
        }

    def test_a_sync_where_nothing_changed_records_every_list_empty(self):
        """Example 2: the one where nothing moved -- attached, not absent (R11.4 row 3)."""
        reports = [SourceReport(source_id="incidents-manual", known=3, fetched=3)]

        assert json.loads(changes_artifact(reports)) == {
            "changed": [],
            "returned": [],
            "tombstoned": [],
        }

    def test_the_record_is_the_same_bytes_whatever_order_the_sources_ran_in(self):
        """The one where two sources report; the artifact is in source order anyway (R0.4)."""
        jira = SourceReport(source_id="incidents-jira", departed=("INC-4821",))
        manual = SourceReport(source_id="incidents-manual", departed=("audit-note.pdf",))

        assert changes_artifact([manual, jira]) == changes_artifact([jira, manual])
