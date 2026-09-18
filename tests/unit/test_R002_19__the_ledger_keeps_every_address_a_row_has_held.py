"""R2.19 — every address a ledger row has ever held is retained in an append-only
`revisions` table.

The store keeps every snapshot (R0.2) and the ledger forgot which item each one
belonged to: after a repoint the previous address was recoverable only by
elimination. A revision row is written in the same transaction as the `items`
row it describes, so the two cannot disagree (R2.8).

The rows are driven through the real `Ledger` directly, with the addresses R2.2
row 3 gives `INC-4822`: `0e52dd18` before the edit, `77c1b40a` after.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dossier.application.sync import sync_source
from dossier.domain.ledger import LedgerRow, Revision
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.store import snapshot_path
from dossier.domain.sync import State
from dossier.infrastructure.ledger import LEDGER_PATH, Ledger
from dossier.infrastructure.store import SnapshotStore

SOURCE = "incidents-jira"
BEFORE = "0e52dd18" + "0" * 56
AFTER = "77c1b40a" + "0" * 56
FIRST = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
SECOND = FIRST + timedelta(days=1)
THIRD = SECOND + timedelta(days=1)


def row(
    key: str, digest: str, *, seen: datetime, first_seen: datetime | None = None
) -> LedgerRow:
    """A row for a source declaring no `fields`, so content and snapshot coincide (R2.10)."""
    return LedgerRow(
        source_id=SOURCE,
        key=key,
        remote_version=None,
        content_hash=digest,
        media_type="text/markdown",
        snapshot_path=snapshot_path(digest),
        first_seen=first_seen or seen,
        last_seen=seen,
        state=State.ACTIVE,
    )


def revision(key: str, digest: str, *, at: datetime) -> Revision:
    return Revision(
        source_id=SOURCE,
        key=key,
        content_hash=digest,
        snapshot_path=snapshot_path(digest),
        recorded_at=at,
    )


class Killed(BaseException):
    """The process stopping where it stands, as a kill or a Ctrl-C would stop it."""


class Tracker:
    """`INC-4822` with no version marker, at whatever bytes it is handed."""

    lists_everything = False

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        yield ItemRef(key="INC-4822", remote_version=None, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        return RawItem(key=key, payload=self.payload, media_type="text/markdown")

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


class KilledBeforeTheRow:
    """The real ledger, except the process dies as it goes to repoint the row (R2.8 row 1)."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def record(self, row: LedgerRow) -> None:
        raise Killed("between writing the snapshot and updating the row")

    def __getattr__(self, name: str):
        return getattr(self._ledger, name)


class TestTheLedgerKeepsEveryAddressARowHasHeld:
    """R2.19 — every address a ledger row has ever held is retained in an append-only table."""

    def test_a_repointed_row_leaves_both_addresses_behind(self, tmp_path: Path):
        """Example 1: the one where `INC-4822` moved and the ledger still knows from where."""
        with Ledger(tmp_path) as ledger:
            ledger.record(row("INC-4822", BEFORE, seen=FIRST))
            ledger.record(row("INC-4822", AFTER, seen=SECOND, first_seen=FIRST))

            assert ledger.row(SOURCE, "INC-4822").content_hash == AFTER
            assert ledger.revisions(SOURCE, "INC-4822") == [
                revision("INC-4822", BEFORE, at=FIRST),
                revision("INC-4822", AFTER, at=SECOND),
            ]

    def test_the_history_starts_at_first_sight(self, tmp_path: Path):
        """Example 2: the one where `INC-4901` is new, and its first version is already kept.

        Otherwise the first version is exactly the one nobody can recover.
        """
        with Ledger(tmp_path) as ledger:
            ledger.record(row("INC-4901", BEFORE, seen=FIRST))

            assert ledger.revisions(SOURCE, "INC-4901") == [
                revision("INC-4901", BEFORE, at=FIRST)
            ]

    def test_returning_to_old_bytes_is_a_third_row(self, tmp_path: Path):
        """Example 3: the one where `INC-4822` went there and back; order is the record."""
        with Ledger(tmp_path) as ledger:
            ledger.record(row("INC-4822", BEFORE, seen=FIRST))
            ledger.record(row("INC-4822", AFTER, seen=SECOND, first_seen=FIRST))
            ledger.record(row("INC-4822", BEFORE, seen=THIRD, first_seen=FIRST))

            assert [r.content_hash for r in ledger.revisions(SOURCE, "INC-4822")] == [
                BEFORE,
                AFTER,
                BEFORE,
            ]

    def test_a_ledger_that_predates_the_table_is_seeded_from_what_it_holds(
        self, tmp_path: Path
    ):
        """Example 4: the one where the ledger was written before revisions existed.

        Seeded with one row per `items` row, `recorded_at` set to that row's
        `last_seen` -- the last sync that confirmed those bytes, which is the
        most the old table can honestly say.
        """
        with Ledger(tmp_path) as ledger:
            ledger.record(row("INC-4821", BEFORE, seen=FIRST))
            ledger.record(row("INC-4822", AFTER, seen=SECOND))
        connection = sqlite3.connect(tmp_path / LEDGER_PATH)
        connection.execute("DROP TABLE revisions")
        connection.commit()
        connection.close()

        with Ledger(tmp_path) as reopened:
            assert reopened.revisions(SOURCE, "INC-4821") == [
                revision("INC-4821", BEFORE, at=FIRST)
            ]
            assert reopened.revisions(SOURCE, "INC-4822") == [
                revision("INC-4822", AFTER, at=SECOND)
            ]

    def test_an_unchanged_item_seen_again_adds_nothing(self, tmp_path: Path):
        """Counter-example (row 5): the one where `audit-note.pdf` was re-read to the same hash.

        A touch is the only write an unchanged item causes, and it is not a
        revision: R2.9 still holds.
        """
        with Ledger(tmp_path) as ledger:
            ledger.record(row("audit-note.pdf", BEFORE, seen=FIRST))
            ledger.touch(SOURCE, "audit-note.pdf", seen_at=SECOND)

            assert ledger.revisions(SOURCE, "audit-note.pdf") == [
                revision("audit-note.pdf", BEFORE, at=FIRST)
            ]

    def test_a_tombstone_is_not_a_revision(self, tmp_path: Path):
        """Counter-example (row 6): the one where `INC-4821` left; state is not content."""
        with Ledger(tmp_path) as ledger:
            ledger.record(row("INC-4821", BEFORE, seen=FIRST))
            ledger.set_state(SOURCE, ["INC-4821"], State.TOMBSTONED)

            assert ledger.revisions(SOURCE, "INC-4821") == [
                revision("INC-4821", BEFORE, at=FIRST)
            ]

    def test_a_history_is_per_key(self, tmp_path: Path):
        """The one where two rows moved and neither history mentions the other."""
        with Ledger(tmp_path) as ledger:
            ledger.record(row("INC-4821", BEFORE, seen=FIRST))
            ledger.record(row("INC-4822", AFTER, seen=FIRST))

            assert [r.key for r in ledger.revisions(SOURCE, "INC-4821")] == ["INC-4821"]
            assert ledger.revisions(SOURCE, "INC-4901") == []

    def test_a_sync_killed_before_the_repoint_leaves_no_revision(self, tmp_path: Path):
        """Counter-example (row 7): the one killed after storing the snapshot, before the row.

        The history never claims a repoint the `items` table does not show: the
        orphan snapshot is inert (R2.8), and the one revision is still the first.
        """
        config = SourceConfig(id=SOURCE, type="issues")
        first, edited = b"# INC-4822 v1", b"# INC-4822 v2"
        with Ledger(tmp_path) as ledger:
            sync_source(
                config=config,
                connector=Tracker(first),
                store=SnapshotStore(tmp_path),
                ledger=ledger,
                now=FIRST,
            )
            with pytest.raises(Killed):
                sync_source(
                    config=config,
                    connector=Tracker(edited),
                    store=SnapshotStore(tmp_path),
                    ledger=KilledBeforeTheRow(ledger),
                    now=SECOND,
                )

            assert [r.content_hash for r in ledger.revisions(SOURCE, "INC-4822")] == [
                hashlib.sha256(first).hexdigest()
            ]
            assert (
                ledger.row(SOURCE, "INC-4822").content_hash == hashlib.sha256(first).hexdigest()
            )
