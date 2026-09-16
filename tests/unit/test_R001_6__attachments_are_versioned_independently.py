"""R1.6 — attachments are addressable and versioned independently of their item.

An issue can be untouched while the PDF attached to it was replaced. So an
attachment carries a marker of its own, not its item's, and is fetched by its own
key (spec 001). R2.6 is what sync does about that; this is the claim about the
connector's answers, and about the independence itself.

The tracker stands in for the Jira connector spec 001 lists as in scope: issues
as JSON, attachments separate.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dossier.application.sync import sync_source
from dossier.domain.ledger import LedgerRow
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

SOURCE = SourceConfig(id="incidents-jira", type="jira")
FIRST = datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC)
LATER = FIRST + timedelta(days=1)

REPORT = "INC-4821/report.pdf"
REPORT_V1 = b"%PDF-1.4\nreport, as filed\n"
REPORT_V2 = b"%PDF-1.4\nreport, revised after review\n"

# An image the issue description embeds, rather than a file hanging off it.
INLINE_IMAGE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="


def issue(key: str, *, body: str = "Batch failed") -> bytes:
    return f'{{"key": "{key}", "description": "{body}"}}'.encode()


class IssueTracker:
    """Issues as JSON, attachments separate, each versioned on its own."""

    def __init__(self, items: dict[str, tuple[bytes, str]]) -> None:
        # key -> (payload, remote_version), for items and attachments alike.
        self.items = dict(items)
        self.attached: dict[str, dict[str, tuple[bytes, str]]] = {}
        self.fetched: list[str] = []

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.items):
            yield ItemRef(key=key, remote_version=self.items[key][1], updated_at=None)

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        for carried in self.attached.values():
            if key in carried:
                payload, version = carried[key]
                return RawItem(
                    key=key,
                    payload=payload,
                    media_type="application/pdf",
                    remote_version=version,
                )
        payload, version = self.items[key]
        return RawItem(
            key=key, payload=payload, media_type="application/json", remote_version=version
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        carried = self.attached.get(key, {})
        for attachment in sorted(carried):
            yield AttachmentRef(
                key=attachment, item_key=key, remote_version=carried[attachment][1]
            )


def sync(workspace: Path, tracker: IssueTracker, *, now: datetime) -> None:
    with Ledger(workspace) as ledger:
        sync_source(
            config=SOURCE,
            connector=tracker,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
        )


def rows(workspace: Path) -> dict[str, LedgerRow]:
    with Ledger(workspace) as ledger:
        return {row.key: row for row in ledger.rows(SOURCE.id)}


def snapshots(workspace: Path) -> list[Path]:
    root = workspace / ".dossier" / "snapshots"
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.is_dir() else []


@pytest.fixture
def tracker(tmp_path: Path) -> IssueTracker:
    """`INC-4821` at `v37`, carrying `report.pdf` at `a1`, both held."""
    issues = IssueTracker({"INC-4821": (issue("INC-4821"), "v37")})
    issues.attached["INC-4821"] = {REPORT: (REPORT_V1, "a1")}
    sync(tmp_path, issues, now=FIRST)
    issues.fetched.clear()
    return issues


class TestAttachmentsAreVersionedIndependently:
    """R1.6 — an attachment has its own address and its own version marker."""

    def test_a_replaced_attachment_moves_only_its_own_marker(
        self, tmp_path: Path, tracker: IssueTracker
    ):
        """Example 1: the one where `report.pdf` is replaced and `INC-4821` is not.

        The listing still reports `v37` -- correctly, the issue did not change --
        while `attachments()` reports a new marker. Independent versioning is
        what makes that expressible at all.
        """
        held = rows(tmp_path)[REPORT]
        tracker.attached["INC-4821"][REPORT] = (REPORT_V2, "a2")

        listed = list(tracker.list())
        attached = list(tracker.attachments("INC-4821"))
        sync(tmp_path, tracker, now=LATER)

        assert [ref.remote_version for ref in listed] == ["v37"]
        assert [ref.remote_version for ref in attached] == ["a2"]
        replaced = rows(tmp_path)[REPORT]
        assert replaced.remote_version == "a2"
        assert replaced.content_hash != held.content_hash
        assert (tmp_path / ".dossier" / "snapshots" / replaced.snapshot_path).is_file()

    def test_a_changed_item_does_not_refetch_its_unchanged_attachment(
        self, tmp_path: Path, tracker: IssueTracker
    ):
        """Example 2: the one where the issue moves and the PDF does not.

        The item is re-snapshotted; the attachment is not even fetched. The
        dependency runs in neither direction, which is the point of the rule.
        """
        held = rows(tmp_path)[REPORT]
        tracker.items["INC-4821"] = (issue("INC-4821", body="Batch failed, reopened"), "v38")

        sync(tmp_path, tracker, now=LATER)

        assert tracker.fetched == ["INC-4821"]
        assert rows(tmp_path)[REPORT].content() == held.content()
        assert rows(tmp_path)["INC-4821"].remote_version == "v38"

    def test_two_issues_carrying_identical_attachments_share_one_snapshot(self, tmp_path: Path):
        """Example 3: the one where the same PDF hangs off two issues.

        One snapshot, referenced twice: content addressing deduplicates, and an
        attachment is addressed by what it contains like everything else (R0.2).
        """
        tracker = IssueTracker(
            {"INC-4821": (issue("INC-4821"), "v37"), "INC-4822": (issue("INC-4822"), "v12")}
        )
        tracker.attached = {
            "INC-4821": {REPORT: (REPORT_V1, "a1")},
            "INC-4822": {"INC-4822/report.pdf": (REPORT_V1, "b1")},
        }

        sync(tmp_path, tracker, now=FIRST)

        held = rows(tmp_path)
        assert held[REPORT].snapshot == held["INC-4822/report.pdf"].snapshot
        assert len(snapshots(tmp_path)) == 3, "two issues and the one PDF they share"

    def test_an_inline_image_is_part_of_the_item_and_has_no_address(self, tmp_path: Path):
        """Counter-example (row 4): the one where the image is in the description.

        Embedded in the payload, so it is not an attachment: it has no key of
        its own, no marker of its own, and nothing to version independently. It
        travels inside the item's snapshot, byte for byte (R1.2).
        """
        payload = issue("INC-4821", body=INLINE_IMAGE)
        tracker = IssueTracker({"INC-4821": (payload, "v37")})

        sync(tmp_path, tracker, now=FIRST)

        held = rows(tmp_path)
        assert list(held) == ["INC-4821"]
        assert list(tracker.attachments("INC-4821")) == []
        stored = tmp_path / ".dossier" / "snapshots" / held["INC-4821"].snapshot_path
        assert INLINE_IMAGE.encode() in stored.read_bytes()
