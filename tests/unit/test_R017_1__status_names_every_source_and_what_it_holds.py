"""R17.1 — `dossier status` names every source, with the documents it holds
active and tombstoned and when it last synced.

The decision is `source_lines`: what the ledger holds per source, and the
sources `sources.yaml` declares, in; the lines `status` prints, out. The values
are `_fixtures.md`'s: `incidents-jira` last synced at `2026-08-06T09:00:00Z`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dossier.domain.status import Held, source_lines
from dossier.domain.sync import State

SYNCED = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


class TestStatusNamesEverySourceAndWhatItHolds:
    """R17.1 — held, tombstoned and last synced, for every source."""

    def test_a_synced_source_says_what_it_holds_and_when_it_last_synced(self):
        """Row 1 — the one where `incidents-jira` holds three issues."""
        lines = source_lines(
            ["incidents-jira"],
            {"incidents-jira": Held(active=3, tombstoned=0, last_synced=SYNCED)},
        )

        assert lines == [
            "incidents-jira · 3 held · 0 tombstoned · last synced 2026-08-06T09:00:00Z"
        ]

    def test_a_tombstoned_document_is_counted_apart_not_dropped(self):
        """Row 2 — the one where `handover-note.md` left `incidents-manual`."""
        held = Held.of([State.ACTIVE, State.TOMBSTONED], last_synced=SYNCED)

        (line,) = source_lines(["incidents-manual"], {"incidents-manual": held})

        assert "· 1 held · 1 tombstoned ·" in line

    def test_a_source_never_synced_says_so_with_no_counts(self):
        """Row 3, counter-example — the one `procedures-confluence` has not synced yet.

        No counts: `0 held` would say a sync ran and found nothing, which is a
        different state from no sync at all.
        """
        assert source_lines(["procedures-confluence"], {}) == [
            "procedures-confluence · never synced"
        ]

    def test_a_source_no_longer_declared_is_still_named_after_the_rest(self):
        """Row 4, counter-example — the one the ledger holds and `sources.yaml` dropped.

        Its documents are still held, and still resolvable by the runs that
        pinned them (R2.7). Leaving it out would make them invisible.
        """
        lines = source_lines(
            ["incidents-manual"],
            {
                "incidents-jira": Held(active=3, tombstoned=0, last_synced=SYNCED),
                "incidents-manual": Held(active=1, tombstoned=0, last_synced=SYNCED),
            },
        )

        assert lines == [
            "incidents-manual · 1 held · 0 tombstoned · last synced 2026-08-06T09:00:00Z",
            "incidents-jira · 3 held · 0 tombstoned · last synced 2026-08-06T09:00:00Z"
            " · not in sources.yaml",
        ]
