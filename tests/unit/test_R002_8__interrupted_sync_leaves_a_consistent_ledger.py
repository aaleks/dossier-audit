"""R2.8 — an interrupted sync leaves a consistent ledger.

Every row present refers to a snapshot that exists and hashes to the recorded
value. The failure mode this rules out is a ledger claiming content the store
does not hold, which turns into an unresolvable run months later.

`incidents-jira` is synced once, successfully. `INC-4822` then moves, and the
second sync is interrupted while handling it: either after its snapshot is
stored and before its row is updated, or in the middle of writing the snapshot.
An interruption is a `BaseException`, as `KeyboardInterrupt` is -- nothing in
the sync may swallow it and carry on as if the item had been handled.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dossier.application.sync import SourceReport, sync_source
from dossier.domain.hashing import content_hash
from dossier.domain.ledger import LedgerRow
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

SOURCE = SourceConfig(id="incidents-jira", type="jira")
FIRST = datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC)
INTERRUPTED = FIRST + timedelta(days=1)
RESUMED = INTERRUPTED + timedelta(hours=1)


class Killed(BaseException):
    """The process stopping where it stands, as a kill or a Ctrl-C would stop it."""


class IssueTracker:
    """Issues at version markers it vouches for. It counts what it is asked to fetch."""

    media_type = "application/json"

    def __init__(self, items: dict[str, str]) -> None:
        self.items = dict(items)
        self.fetched: list[str] = []

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.items):
            yield ItemRef(key=key, remote_version=self.items[key], updated_at=None)

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        return RawItem(
            key=key,
            payload=payload(key, self.items[key]),
            media_type=self.media_type,
            remote_version=self.items[key],
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


class KilledBeforeTheRow:
    """The real ledger, except the process dies as it goes to record `INC-4822`."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def record(self, row: LedgerRow) -> None:
        if row.key == "INC-4822":
            raise Killed("between writing the snapshot and updating the row")
        self._ledger.record(row)

    def __getattr__(self, name: str):
        return getattr(self._ledger, name)


def payload(key: str, version: str) -> bytes:
    return f'{{"key": "{key}", "version": "{version}"}}'.encode()


def sync(workspace: Path, tracker: IssueTracker, *, now: datetime, wrap=None) -> SourceReport:
    with Ledger(workspace) as ledger:
        return sync_source(
            config=SOURCE,
            connector=tracker,
            store=SnapshotStore(workspace),
            ledger=wrap(ledger) if wrap else ledger,
            now=now,
        )


def rows(workspace: Path) -> list[LedgerRow]:
    with Ledger(workspace) as ledger:
        return ledger.rows(SOURCE.id)


def interrupted_row(workspace: Path) -> LedgerRow | None:
    """`INC-4822`'s row, the item the sync was handling when it stopped.

    Only its row is compared. `INC-4821`, handled before the interruption, has
    rightly been seen again, and its `last_seen` moving is a record of that.
    """
    with Ledger(workspace) as ledger:
        return ledger.row(SOURCE.id, "INC-4822")


def watermark(workspace: Path) -> datetime | None:
    with Ledger(workspace) as ledger:
        return ledger.watermark(SOURCE.id)


def assert_consistent(workspace: Path) -> None:
    """The invariant: every row names a snapshot that exists and hashes to its hash."""
    store = SnapshotStore(workspace)
    for row in rows(workspace):
        assert content_hash(store.get(row.content_hash)) == row.content_hash, row.key


@pytest.fixture
def tracker(tmp_path: Path) -> IssueTracker:
    """`INC-4821` and `INC-4822`, both held after a first sync; then `INC-4822` moves."""
    issues = IssueTracker({"INC-4821": "v37", "INC-4822": "v12"})
    sync(tmp_path, issues, now=FIRST)
    issues.items["INC-4822"] = "v13"
    issues.fetched.clear()
    return issues


def killed_mid_write(monkeypatch) -> None:
    """The next snapshot write dies after its bytes are written, before they are in place."""

    def die(descriptor: int) -> None:
        raise Killed("in the middle of writing a snapshot")

    monkeypatch.setattr("dossier.infrastructure.store.os.fsync", die)


class TestInterruptedSyncLeavesAConsistentLedger:
    """R2.8 — an interrupted sync leaves a consistent ledger."""

    def test_killed_between_the_snapshot_and_the_row(self, tmp_path: Path, tracker):
        """Example 1: the one killed after storing `INC-4822`'s snapshot, before its row.

        The row still holds the previous hash. The new snapshot stays -- the
        store never deletes (R0.2) -- but no row refers to it, so it is inert.
        """
        before = interrupted_row(tmp_path)
        orphan = content_hash(payload("INC-4822", "v13"))

        with pytest.raises(Killed):
            sync(tmp_path, tracker, now=INTERRUPTED, wrap=KilledBeforeTheRow)

        assert interrupted_row(tmp_path) == before
        assert SnapshotStore(tmp_path).exists(orphan)
        assert orphan not in {row.content_hash for row in rows(tmp_path)}
        assert_consistent(tmp_path)

    def test_killed_in_the_middle_of_writing_a_snapshot(
        self, tmp_path: Path, tracker, monkeypatch
    ):
        """Example 2: the one killed mid-write of `INC-4822`'s snapshot.

        Nothing sits at the content address the partial bytes would have had,
        and no row refers to them: they are never treated as content.
        """
        before = interrupted_row(tmp_path)
        partial = content_hash(payload("INC-4822", "v13"))
        killed_mid_write(monkeypatch)

        with pytest.raises(Killed):
            sync(tmp_path, tracker, now=INTERRUPTED)

        assert not SnapshotStore(tmp_path).exists(partial)
        assert interrupted_row(tmp_path) == before
        assert_consistent(tmp_path)

    @pytest.mark.parametrize("interruption", ["before the row", "mid-write"])
    def test_a_resumed_sync_completes(self, tmp_path: Path, tracker, monkeypatch, interruption):
        """Example 3: the one resumed after either interruption.

        It completes: `INC-4822` is fetched again and committed normally, as if
        the interrupted attempt had never been made.
        """
        with monkeypatch.context() as scope, pytest.raises(Killed):
            if interruption == "mid-write":
                killed_mid_write(scope)
                sync(tmp_path, tracker, now=INTERRUPTED)
            else:
                sync(tmp_path, tracker, now=INTERRUPTED, wrap=KilledBeforeTheRow)
        tracker.fetched.clear()

        report = sync(tmp_path, tracker, now=RESUMED)

        assert report.failed == ()
        assert tracker.fetched == ["INC-4822"]
        committed = next(row for row in rows(tmp_path) if row.key == "INC-4822")
        assert committed.content_hash == content_hash(payload("INC-4822", "v13"))
        assert committed.last_seen == RESUMED
        assert_consistent(tmp_path)

    def test_the_watermark_does_not_advance(self, tmp_path: Path, tracker):
        """Counter-example (row 4): the one reading `last_sync_at` after the interruption.

        Not advanced: a partial sync must not be mistaken for a complete one.
        Had it moved, the resumed sync would ask only for what changed since the
        interruption, and `INC-4822` would be found only by the overlap's grace.
        """
        with pytest.raises(Killed):
            sync(tmp_path, tracker, now=INTERRUPTED, wrap=KilledBeforeTheRow)

        assert watermark(tmp_path) == FIRST
