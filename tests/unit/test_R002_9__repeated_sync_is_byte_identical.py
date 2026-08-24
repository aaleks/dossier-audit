"""R2.9 — two syncs over an unchanged source produce byte-identical ledger content.

Apart from `last_seen` and `last_sync_at`, which are the only fields that record
*when* rather than *what*.

Proved here for the ledger itself. Example 1 is stated in terms of two runs of
`dossier sync`, which needs the use case and the CLI -- so this rule stays
NOT MET until those exist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dossier.domain.ledger import LedgerRow
from dossier.domain.sync import State
from dossier.infrastructure.ledger import Ledger

FIRST = datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC)
LATER = FIRST + timedelta(days=1)


def row(*, key: str = "INC-4821", seen: datetime = FIRST, **overrides) -> LedgerRow:
    defaults = {
        "source_id": "incidents-manual",
        "key": key,
        "remote_version": None,
        "content_hash": "a" * 64,
        "snapshot_path": "aa/aa/" + "a" * 64,
        "first_seen": seen,
        "last_seen": seen,
    }
    return LedgerRow(**(defaults | overrides))


class TestLedgerContentIsStable:
    """R2.9 — only the two time columns may move."""

    def test_recording_the_same_item_twice_changes_only_last_seen(self, tmp_path: Path):
        """The one where the second sync found nothing new.

        Compared through `content()`, which excludes `last_seen` on purpose --
        that is exactly the exemption the rule grants.
        """
        with Ledger(tmp_path) as ledger:
            ledger.record(row())
            after_first = ledger.rows("incidents-manual")

            ledger.record(row(seen=LATER))
            after_second = ledger.rows("incidents-manual")

        assert [r.content() for r in after_second] == [r.content() for r in after_first]
        assert after_second[0].last_seen != after_first[0].last_seen

    def test_first_seen_is_never_rewritten(self, tmp_path: Path):
        """Counter-example (row 4): the one where the answer is identical by construction.

        `first_seen` answers "since when have we held this". A later sync that
        moved it would be lying, and R2.7 example 3 depends on it surviving an
        item leaving scope and coming back.
        """
        with Ledger(tmp_path) as ledger:
            ledger.record(row())
            ledger.record(row(seen=LATER, first_seen=LATER))

            (stored,) = ledger.rows("incidents-manual")

        assert stored.first_seen == FIRST

    def test_touching_an_unchanged_item_moves_only_last_seen(self, tmp_path: Path):
        """The one write an unchanged item causes.

        R2.5 counts snapshots written, not ledger touches: an item can be seen
        again without anything being stored.
        """
        with Ledger(tmp_path) as ledger:
            ledger.record(row())
            before = ledger.row("incidents-manual", "INC-4821")

            ledger.touch("incidents-manual", "INC-4821", seen_at=LATER)
            after = ledger.row("incidents-manual", "INC-4821")

        assert after.content() == before.content()
        assert after.last_seen == LATER

    def test_rows_come_back_in_a_stable_order(self, tmp_path: Path):
        """The one where insertion order must not leak into a comparison.

        An unordered read is machine-dependent, and this rule compares ledger
        content between two syncs (R5.6).
        """
        with Ledger(tmp_path) as ledger:
            for key in ["INC-4822", "audit-note.pdf", "INC-4821"]:
                ledger.record(row(key=key))

            assert [r.key for r in ledger.rows("incidents-manual")] == [
                "INC-4821",
                "INC-4822",
                "audit-note.pdf",
            ]

    def test_the_ledger_survives_being_reopened(self, tmp_path: Path):
        """The one where a sync is a separate process from the one before it."""
        with Ledger(tmp_path) as ledger:
            ledger.record(row())
            ledger.set_watermark("incidents-manual", FIRST)

        with Ledger(tmp_path) as reopened:
            assert [r.content() for r in reopened.rows("incidents-manual")] == [row().content()]
            assert reopened.watermark("incidents-manual") == FIRST

    def test_a_source_that_has_never_synced_has_no_watermark(self, tmp_path: Path):
        """The one R2.4's counter-example depends on."""
        with Ledger(tmp_path) as ledger:
            assert ledger.watermark("incidents-manual") is None

    def test_tombstoning_changes_state_and_keeps_everything_else(self, tmp_path: Path):
        """R2.7: the one where the row and its snapshot both remain."""
        with Ledger(tmp_path) as ledger:
            ledger.record(row())
            ledger.set_state("incidents-manual", ["INC-4821"], State.TOMBSTONED)

            (stored,) = ledger.rows("incidents-manual")

        assert stored.state is State.TOMBSTONED
        assert stored.content_hash == "a" * 64
        assert stored.snapshot_path == "aa/aa/" + "a" * 64

    def test_a_naive_timestamp_is_refused(self, tmp_path: Path):
        """The one where a stored time would read back differently elsewhere.

        A naive timestamp means something different on every machine, and this
        rule compares ledger content across syncs (R0.4).
        """
        with Ledger(tmp_path) as ledger, pytest.raises(ValueError):
            ledger.record(row(seen=datetime(2026, 8, 6, 9, 0, 0)))

    def test_two_sources_do_not_share_rows(self, tmp_path: Path):
        """The one the duplicate-id check in config exists to protect.

        The ledger is keyed by (source_id, key), so the same key in two sources
        is two rows.
        """
        with Ledger(tmp_path) as ledger:
            ledger.record(row())
            ledger.record(row(source_id="incidents-jira"))

            assert len(ledger.rows("incidents-manual")) == 1
            assert len(ledger.rows("incidents-jira")) == 1
