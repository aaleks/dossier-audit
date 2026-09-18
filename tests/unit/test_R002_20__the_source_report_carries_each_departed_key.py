"""R2.20 — the sync report carries each key it tombstoned, so the command can name it.

`tombstones()` already decides which keys departed (R2.7); `SourceReport` was
reducing that to a count. This is the report carrying the keys out, in key
order, from both places a departure is decided: the full listing an item is
absent from, and the item an attachment is no longer carried by (R2.6 row 3).

The tracker has no watermark on its first sync, so that listing is full and
tombstones against it are computed; a second sync is incremental unless the
projection changed. The tests below get a full second listing the way a
workspace does, by changing `fields` (R2.3).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
ATTACHMENT = "INC-4821/report.pdf"


class Tracker:
    """Two issues, one carrying an attachment; listed in reverse so order is earned."""

    lists_everything = False

    def __init__(self) -> None:
        self.issues = {"INC-4821": b'{"key": "INC-4821"}', "INC-4822": b'{"key": "INC-4822"}'}
        self.attached = {ATTACHMENT: b"%PDF-1.4"}

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.issues, reverse=True):
            yield ItemRef(key=key, remote_version=None, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        if key in self.attached:
            return RawItem(key=key, payload=self.attached[key], media_type="application/pdf")
        return RawItem(key=key, payload=self.issues[key], media_type="application/json")

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        for attachment in sorted(self.attached):
            if attachment.startswith(f"{key}/"):
                yield AttachmentRef(key=attachment, item_key=key, remote_version=None)


def sync(workspace: Path, tracker: Tracker, *, fields: list[str]):
    with Ledger(workspace) as ledger:
        return sync_source(
            config=SourceConfig(id="incidents-jira", type="issues", fields=fields),
            connector=tracker,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=NOW,
        )


class TestTheSourceReportCarriesEachDepartedKey:
    """R2.20 — the sync report carries each key it tombstoned, so the command can name it."""

    def test_both_departures_are_carried_in_key_order(self, tmp_path: Path):
        """Example 2: the one where both issues left, listed by nobody, named in key order.

        The attachment goes with its item: it is a row of its own (R1.6), absent
        from the same full listing.
        """
        tracker = Tracker()
        sync(tmp_path, tracker, fields=["key"])
        tracker.issues.clear()
        tracker.attached.clear()

        report = sync(tmp_path, tracker, fields=["key", "summary"])

        assert report.tombstoned == 3
        assert report.departed == ("INC-4821", "INC-4821/report.pdf", "INC-4822")

    def test_a_removed_attachment_is_carried_under_an_incremental_listing(self, tmp_path: Path):
        """The one where `INC-4821` stayed and its `report.pdf` did not (R2.6 row 3).

        The one departure that needs no full listing: `attachments(key)` answers
        for the item completely, so the report names it on an ordinary sync.
        """
        tracker = Tracker()
        sync(tmp_path, tracker, fields=["key"])
        tracker.attached.clear()

        report = sync(tmp_path, tracker, fields=["key"])

        assert (report.tombstoned, report.departed) == (1, ("INC-4821/report.pdf",))

    def test_an_incremental_listing_carries_nothing(self, tmp_path: Path):
        """Counter-example (row 3): the one where an issue is absent from a windowed listing."""
        tracker = Tracker()
        sync(tmp_path, tracker, fields=["key"])
        del tracker.issues["INC-4822"]

        report = sync(tmp_path, tracker, fields=["key"])

        assert (report.tombstoned, report.departed) == (0, ())
