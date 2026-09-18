"""R2.6 — a replaced attachment is detected under an otherwise unchanged item.

An issue can be untouched while the PDF attached to it was replaced. The item's
version marker says nothing about that, so an attachment carries its own marker,
its own hash and its own ledger row (R1.6).

`INC-4821` sits at `v37` throughout. Only `report.pdf` moves: replaced, then
removed, then -- in the counter-example -- renamed with its bytes untouched. An
attachment is addressed as an item is, so `fetch` takes its key (spec 001).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dossier.application.sync import SourceReport, sync_source
from dossier.domain.keys import ConvertInputs, cache_key
from dossier.domain.ledger import LedgerRow
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.sync import State
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

SOURCE = SourceConfig(id="incidents-jira", type="jira")
ITEM = "INC-4821"
REPORT = "INC-4821/report.pdf"
RENAMED = "INC-4821/final-report.pdf"

FIRST = datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC)
LATER = FIRST + timedelta(days=1)

ISSUE = b'{"key": "INC-4821", "summary": "Batch failed"}'
REPORT_V1 = b"%PDF-1.4\nreport, as filed\n"
REPORT_V2 = b"%PDF-1.4\nreport, revised after review\n"


class IssueTracker:
    """One issue at `v37`, carrying attachments it versions independently."""

    lists_everything = False

    def __init__(self) -> None:
        # key -> (payload, remote_version). The issue itself never moves.
        self.attached: dict[str, tuple[bytes, str]] = {REPORT: (REPORT_V1, "a1")}
        self.fetched: list[str] = []

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        yield ItemRef(key=ITEM, remote_version="v37", updated_at=None)

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        if key == ITEM:
            return RawItem(
                key=key, payload=ISSUE, media_type="application/json", remote_version="v37"
            )
        payload, version = self.attached[key]
        return RawItem(
            key=key, payload=payload, media_type="application/pdf", remote_version=version
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        for attachment in sorted(self.attached):
            yield AttachmentRef(
                key=attachment, item_key=key, remote_version=self.attached[attachment][1]
            )


def sync(workspace: Path, tracker: IssueTracker, *, now: datetime) -> SourceReport:
    with Ledger(workspace) as ledger:
        return sync_source(
            config=SOURCE,
            connector=tracker,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
        )


def row_for(workspace: Path, key: str) -> LedgerRow | None:
    with Ledger(workspace) as ledger:
        return ledger.row(SOURCE.id, key)


def snapshot_count(workspace: Path) -> int:
    root = workspace / ".dossier" / "snapshots"
    return len([path for path in root.rglob("*") if path.is_file()]) if root.is_dir() else 0


def convert_key(row: LedgerRow) -> str:
    """The convert key over what this row holds, as a run would compute it (R5.4)."""
    return cache_key(
        ConvertInputs(
            snapshot=row.snapshot, converter_id="pdf-markdown", converter_version="1.3.0"
        )
    )


@pytest.fixture
def tracker(tmp_path: Path) -> IssueTracker:
    """`INC-4821` and its `report.pdf`, both held after one sync."""
    issues = IssueTracker()
    sync(tmp_path, issues, now=FIRST)
    issues.fetched.clear()
    return issues


class TestReplacedAttachmentIsDetected:
    """R2.6 — a replaced attachment is detected under an otherwise unchanged item."""

    def test_a_replaced_attachment_is_snapshotted_and_the_item_is_not(
        self, tmp_path: Path, tracker: IssueTracker
    ):
        """Example 1: the one where `report.pdf` is replaced under `INC-4821` at `v37`.

        A new attachment snapshot, and the item's own snapshot untouched: the
        issue did not change, and re-snapshotting it would claim it had.
        """
        item_before = row_for(tmp_path, ITEM)
        attachment_before = row_for(tmp_path, REPORT)
        tracker.attached[REPORT] = (REPORT_V2, "a2")

        sync(tmp_path, tracker, now=LATER)

        attachment = row_for(tmp_path, REPORT)
        assert attachment.content_hash != attachment_before.content_hash
        assert (tmp_path / ".dossier" / "snapshots" / attachment.snapshot_path).is_file()
        assert row_for(tmp_path, ITEM).content() == item_before.content()
        assert ITEM not in tracker.fetched

    def test_the_replacement_moves_every_key_derived_from_it(
        self, tmp_path: Path, tracker: IssueTracker
    ):
        """Example 2: the one where the pipeline consumes that attachment.

        The convert key is composed over the snapshot the row holds, so a
        replaced attachment re-converts and every stage above it re-runs (R5.7).
        The item's own key does not move, which is the half that makes this
        affordable.
        """
        before = convert_key(row_for(tmp_path, REPORT))
        item_key_before = convert_key(row_for(tmp_path, ITEM))
        tracker.attached[REPORT] = (REPORT_V2, "a2")

        sync(tmp_path, tracker, now=LATER)

        assert convert_key(row_for(tmp_path, REPORT)) != before
        assert convert_key(row_for(tmp_path, ITEM)) == item_key_before

    def test_a_removed_attachment_is_tombstoned_and_its_item_is_not(
        self, tmp_path: Path, tracker: IssueTracker
    ):
        """Example 3: the one where `report.pdf` is removed from `INC-4821`.

        The attachment row is tombstoned and its snapshot stays resolvable
        (R2.7); the item row stays `active`, because the item is still there.
        """
        tracker.attached.clear()

        sync(tmp_path, tracker, now=LATER)

        assert row_for(tmp_path, REPORT).state is State.TOMBSTONED
        assert row_for(tmp_path, ITEM).state is State.ACTIVE

    def test_a_renamed_attachment_writes_no_new_snapshot(
        self, tmp_path: Path, tracker: IssueTracker
    ):
        """Counter-example (row 4): the one renamed with its bytes untouched.

        The same content hash, so no new snapshot: content addressing does not
        care what a file is called. Only the ledger's key changes -- the old key
        leaves scope and is tombstoned, and the new one holds the same bytes.
        """
        held = row_for(tmp_path, REPORT)
        before = snapshot_count(tmp_path)
        tracker.attached = {RENAMED: (REPORT_V1, "a1")}

        sync(tmp_path, tracker, now=LATER)

        renamed = row_for(tmp_path, RENAMED)
        assert renamed.content_hash == held.content_hash
        assert renamed.snapshot_path == held.snapshot_path
        assert snapshot_count(tmp_path) == before
        assert row_for(tmp_path, REPORT).state is State.TOMBSTONED
