"""R17.1 — `dossier status` names every source, with the documents it holds
active and tombstoned and when it last synced.

The decision is `source_lines`: what the ledger holds per source, and the
sources `sources.yaml` declares, in; the lines `status` prints, out. The values
are `_fixtures.md`'s: `incidents-jira` last synced at `2026-08-06T09:00:00Z`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tests.acceptance.test_R017_7__status_says_what_eval_will_withhold import _cli

from dossier.domain.ledger import LedgerRow
from dossier.domain.status import Held, source_lines
from dossier.domain.sync import State
from dossier.infrastructure.ledger import Ledger, read_held

SYNCED = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


def held_row(source_id: str, key: str) -> LedgerRow:
    """A ledger row as a sync stores it; only its source, key and state are counted."""
    return LedgerRow(
        source_id=source_id,
        key=key,
        remote_version=None,
        content_hash="sha256:c4d1",
        media_type="application/octet-stream",
        snapshot_path=f"snapshots/c4/{key}",
        first_seen=SYNCED,
        last_seen=SYNCED,
    )


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

    def test_a_tombstoned_document_is_counted_apart_not_dropped(self, tmp_path: Path):
        """Row 2 — the one where `handover-note.md` left `incidents-manual`.

        Counted from the ledger as sync leaves it, so the count is of the rows
        a tombstone keeps (R2.7), not of a list handed in.
        """
        with Ledger(tmp_path) as ledger:
            for key in ("audit-note.pdf", "handover-note.md"):
                ledger.record(held_row("incidents-manual", key))
            ledger.set_state("incidents-manual", ["handover-note.md"], State.TOMBSTONED)
            ledger.set_watermark("incidents-manual", SYNCED)

        assert source_lines(["incidents-manual"], read_held(tmp_path)) == [
            "incidents-manual · 1 held · 1 tombstoned · last synced 2026-08-06T09:00:00Z"
        ]

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

    def test_a_source_held_with_no_complete_sync_names_no_watermark(self, tmp_path: Path):
        """Row 5, counter-example — the one whose first sync was refused an export.

        It stored `OPS-115` and was refused `81920114.pdf`, so the watermark
        never moved (R2.8): the ledger holds a document and no instant to
        name. Before this row, `status` raised on the missing instant.
        """
        with Ledger(tmp_path) as ledger:
            ledger.record(held_row("procedures-confluence", "OPS-115"))
            ledger.owe(
                "procedures-confluence",
                "81920114.pdf",
                item_key="81920114",
                at=SYNCED,
                error="answered 403",
            )

        lines = source_lines(["procedures-confluence"], read_held(tmp_path))

        assert lines[0] == (
            "procedures-confluence · 1 held · 0 tombstoned · no complete sync yet"
        )

    def test_with_no_sources_yaml_what_the_ledger_holds_is_still_named(
        self, tmp_path: Path, monkeypatch
    ):
        """Row 6, counter-example — the one whose `sources.yaml` is gone.

        It declares nothing, so every source the ledger holds is one it no
        longer declares. `status` informs, and exits 0 (R17.6).
        """
        with Ledger(tmp_path) as ledger:
            ledger.record(held_row("incidents-jira", "INC-4821"))
            ledger.set_watermark("incidents-jira", SYNCED)

        result = _cli(tmp_path, monkeypatch, "status")

        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[:2] == [
            "sources",
            "  incidents-jira · 1 held · 0 tombstoned · last synced 2026-08-06T09:00:00Z"
            " · not in sources.yaml",
        ]
