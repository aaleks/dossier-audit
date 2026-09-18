"""R2.18 — the sync report carries each repointed item, so the command can name it.

`sync_source` is where the old address is last in hand: the recorded row is read
before the new snapshot is written, and `SourceReport` was throwing that away as
a count. This is the report carrying it out, in key order whatever order the
connector listed in, so the lines a person reads are the same on every machine
(R0.4).

One tracker holding `INC-4821` and `INC-4822` with no version markers, so every
sync reads both and the content hash decides (R2.2).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.sync import Repointed
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

SOURCE = SourceConfig(id="incidents-jira", type="issues")
NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


def address(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class Tracker:
    """Two issues with no version markers; lists them in reverse so order is earned."""

    lists_everything = False

    def __init__(self) -> None:
        self.issues = {"INC-4821": b"# INC-4821 v1\n", "INC-4822": b"# INC-4822 v1\n"}

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.issues, reverse=True):
            yield ItemRef(key=key, remote_version=None, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        return RawItem(key=key, payload=self.issues[key], media_type="text/markdown")

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


def sync(workspace: Path, tracker: Tracker):
    with Ledger(workspace) as ledger:
        return sync_source(
            config=SOURCE,
            connector=tracker,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=NOW,
        )


class TestTheSourceReportCarriesEachRepointedItem:
    """R2.18 — the sync report carries each repointed item, so the command can name it."""

    def test_both_edited_issues_are_carried_in_key_order(self, tmp_path: Path):
        """Example 1: the one where both issues moved, listed by the connector in reverse."""
        tracker = Tracker()
        before = dict(tracker.issues)
        sync(tmp_path, tracker)
        tracker.issues = {"INC-4821": b"# INC-4821 v2\n", "INC-4822": b"# INC-4822 v2\n"}

        report = sync(tmp_path, tracker)

        assert report.changed == 2
        assert report.repointed == (
            Repointed(
                "INC-4821", address(before["INC-4821"]), address(tracker.issues["INC-4821"])
            ),
            Repointed(
                "INC-4822", address(before["INC-4822"]), address(tracker.issues["INC-4822"])
            ),
        )

    def test_a_first_sync_carries_nothing(self, tmp_path: Path):
        """Counter-example (row 5): the one where everything is new -- nothing to name."""
        report = sync(tmp_path, Tracker())

        assert (report.new, report.repointed) == (2, ())
