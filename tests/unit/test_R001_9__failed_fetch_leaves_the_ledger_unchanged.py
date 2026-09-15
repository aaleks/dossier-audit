"""R1.9 — a connector error leaves the ledger unchanged for that item.

Partial sync never records an item it did not successfully store.

`incidents-jira` is synced once, successfully, and then again after its items
move. The hash the first sync records stands for `_fixtures.md`'s `77c1b40a`:
the claim is that the second sync leaves it where it was, whatever it is.
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
LATER = FIRST + timedelta(days=1)


class IssueTracker:
    """Issues at version markers it vouches for, any of which can be made to fail."""

    media_type = "application/json"

    def __init__(self, items: dict[str, str]) -> None:
        self.items = dict(items)
        self.failing: set[str] = set()

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.items):
            yield ItemRef(key=key, remote_version=self.items[key], updated_at=None)

    def fetch(self, key: str) -> RawItem:
        if key in self.failing:
            raise ConnectionError(f"connection reset while fetching {key}")
        return RawItem(
            key=key,
            payload=payload(key, self.items[key]),
            media_type=self.media_type,
            remote_version=self.items[key],
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


class RefusingLedger:
    """The real ledger, except that recording `key` fails -- after its snapshot is stored."""

    def __init__(self, ledger: Ledger, key: str) -> None:
        self._ledger = ledger
        self._key = key

    def record(self, row: LedgerRow) -> None:
        if row.key == self._key:
            raise OSError("killed between writing the snapshot and updating the row")
        self._ledger.record(row)

    def __getattr__(self, name: str):
        return getattr(self._ledger, name)


def payload(key: str, version: str) -> bytes:
    return f'{{"key": "{key}", "version": "{version}"}}'.encode()


def sync(workspace: Path, tracker: IssueTracker, *, now: datetime) -> SourceReport:
    with Ledger(workspace) as ledger:
        return sync_source(
            config=SOURCE,
            connector=tracker,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
        )


def held(workspace: Path, key: str) -> LedgerRow | None:
    with Ledger(workspace) as ledger:
        return ledger.row(SOURCE.id, key)


@pytest.fixture
def tracker(tmp_path: Path) -> IssueTracker:
    """`INC-4821` and `INC-4822`, both held after a first sync that went well."""
    issues = IssueTracker({"INC-4821": "v37", "INC-4822": "v12"})
    first = sync(tmp_path, issues, now=FIRST)
    assert first.failed == ()
    return issues


class TestFailedFetchLeavesTheLedgerUnchanged:
    """R1.9 — a connector error leaves the ledger unchanged for that item."""

    def test_a_changed_item_that_fails_keeps_its_previous_row(
        self, tmp_path: Path, tracker: IssueTracker
    ):
        """Example 1: the one where `INC-4822` raises a connection error during `fetch`.

        Its row keeps the hash it had and the `last_seen` it had: moving either
        would record a sync of `INC-4822` that never happened.
        """
        before = held(tmp_path, "INC-4822")
        tracker.items["INC-4822"] = "v13"
        tracker.failing.add("INC-4822")

        report = sync(tmp_path, tracker, now=LATER)

        assert report.failed == ("INC-4822",)
        assert held(tmp_path, "INC-4822") == before
        assert before.last_seen == FIRST

    def test_a_new_item_that_fails_gets_no_row(self, tmp_path: Path, tracker: IssueTracker):
        """Example 2: the one where `INC-4901` is new and raises during `fetch`."""
        tracker.items["INC-4901"] = "v1"
        tracker.failing.add("INC-4901")

        report = sync(tmp_path, tracker, now=LATER)

        assert report.failed == ("INC-4901",)
        assert held(tmp_path, "INC-4901") is None

    def test_what_succeeded_before_a_failure_is_committed(
        self, tmp_path: Path, tracker: IssueTracker
    ):
        """Example 3: the one where `INC-4821` succeeds, then `INC-4822` fails.

        `INC-4821` is committed, not rolled back with the failure: one bad item
        does not cost the rest of the sync. The failure is reported here; the
        non-zero exit code `dossier sync` turns it into is R2.13's row 4.
        """
        tracker.items["INC-4821"] = "v38"
        tracker.items["INC-4822"] = "v13"
        tracker.failing.add("INC-4822")

        report = sync(tmp_path, tracker, now=LATER)

        assert report.failed == ("INC-4822",)
        committed = held(tmp_path, "INC-4821")
        assert committed.remote_version == "v38"
        assert committed.content_hash == content_hash(payload("INC-4821", "v38"))

    def test_a_failure_after_the_snapshot_is_stored_leaves_it_an_orphan(
        self, tmp_path: Path, tracker: IssueTracker
    ):
        """Counter-example (row 4): the one killed after the snapshot, before the row.

        The ledger stays unchanged, and the snapshot already written stays too --
        the store never deletes (R0.2) -- but nothing refers to it, so it is inert.
        """
        before = held(tmp_path, "INC-4822")
        tracker.items["INC-4822"] = "v13"
        orphan = content_hash(payload("INC-4822", "v13"))
        store = SnapshotStore(tmp_path)

        with Ledger(tmp_path) as ledger, pytest.raises(OSError):
            sync_source(
                config=SOURCE,
                connector=tracker,
                store=store,
                ledger=RefusingLedger(ledger, "INC-4822"),
                now=LATER,
            )

        assert store.exists(orphan)
        assert held(tmp_path, "INC-4822") == before
        with Ledger(tmp_path) as ledger:
            assert orphan not in {row.content_hash for row in ledger.rows(SOURCE.id)}
