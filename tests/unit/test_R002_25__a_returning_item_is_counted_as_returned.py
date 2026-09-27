"""R2.25 — `dossier sync` counts and names each item that returns after it was
tombstoned, apart from known, changed and new.

`known` is the rows active before the sync and `new` the keys never held, so a
tombstoned item offered again was fetched and counted nowhere. The report now
carries it as returned -- with both addresses when its bytes changed while it
was gone -- and the ledger holds it active again whichever listing offered it.

The tracker's first sync is a full listing, and so is one after `fields`
changes (R2.3); any other is windowed. That is how these tests tombstone an
item and then offer it back through either kind of listing.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import ItemRef, RawItem
from dossier.domain.sync import State
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


class Tracker:
    """Issues listed whatever the window: every listing offers every issue it holds."""

    lists_everything = False

    def __init__(self) -> None:
        self.issues = {"INC-4821": b'{"key": "INC-4821"}', "INC-4822": b'{"key": "INC-4822"}'}

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.issues):
            yield ItemRef(key=key, remote_version=None, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        return RawItem(key=key, payload=self.issues[key], media_type="application/json")

    def attachments(self, key: str):
        return iter(())


def sync(workspace: Path, tracker: Tracker, *, fields: list[str], hours: int = 0):
    with Ledger(workspace) as ledger:
        return sync_source(
            config=SourceConfig(id="incidents-jira", type="issues", fields=fields),
            connector=tracker,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=NOW + timedelta(hours=hours),
        )


def state(workspace: Path, key: str) -> State:
    with Ledger(workspace) as ledger:
        return next(row.state for row in ledger.rows("incidents-jira") if row.key == key)


def tombstone_inc_4821(workspace: Path, tracker: Tracker) -> bytes:
    """Sync both, then drop `INC-4821` from a full listing. Returns its bytes."""
    sync(workspace, tracker, fields=["key"])
    held = tracker.issues.pop("INC-4821")
    report = sync(workspace, tracker, fields=["key", "summary"], hours=1)
    assert report.departed == ("INC-4821",)
    return held


class TestAReturningItemIsCountedAsReturned:
    """R2.25 — returned, not known, changed or new; and active again."""

    def test_an_item_back_with_its_bytes_is_returned(self, tmp_path: Path):
        """Row 1: the one where three fetched add up to three.

        One known, and one returned: nothing is counted as changed or new for
        an item the ledger held all along.
        """
        tracker = Tracker()
        tracker.issues["INC-4821"] = tombstone_inc_4821(tmp_path, tracker)

        report = sync(tmp_path, tracker, fields=["key", "summary", "status"], hours=2)

        assert (report.known, report.changed, report.new) == (1, 0, 0)
        assert [(item.key, item.moved) for item in report.returned] == [("INC-4821", None)]
        assert report.fetched == 2

    def test_an_item_back_with_other_bytes_carries_both_addresses(self, tmp_path: Path):
        """Row 2: the one where it changed while it was gone.

        Returned, and not changed: `changed` counts items that were known. The
        two addresses travel with the returned item instead of as a repointing.
        """
        tracker = Tracker()
        tombstone_inc_4821(tmp_path, tracker)
        tracker.issues["INC-4821"] = b'{"key": "INC-4821", "summary": "reopened"}'

        report = sync(tmp_path, tracker, fields=["key", "summary", "status"], hours=2)

        assert report.changed == 0
        assert report.repointed == ()
        (item,) = report.returned
        assert item.key == "INC-4821"
        assert item.moved is not None and item.moved.held != item.moved.now

    def test_a_windowed_listing_brings_an_item_back_too(self, tmp_path: Path):
        """Row 3: the one where only a complete listing used to revive.

        `fields` is unchanged, so this listing is windowed and tombstones
        nothing. It offers `INC-4821` with the bytes it had, and the row is
        active again (R2.7 row 3); before, it stayed tombstoned.
        """
        tracker = Tracker()
        tracker.issues["INC-4821"] = tombstone_inc_4821(tmp_path, tracker)

        report = sync(tmp_path, tracker, fields=["key", "summary"], hours=2)

        assert [item.key for item in report.returned] == ["INC-4821"]
        assert state(tmp_path, "INC-4821") is State.ACTIVE

    def test_nothing_returned_is_nothing_carried(self, tmp_path: Path):
        """Counter-example (row 4): the one where no item came back."""
        tracker = Tracker()
        sync(tmp_path, tracker, fields=["key"])

        report = sync(tmp_path, tracker, fields=["key"], hours=1)

        assert report.returned == ()

    def test_a_key_never_held_is_new_not_returned(self, tmp_path: Path):
        """Counter-example (row 5): the one where `INC-4822` is new to the ledger."""
        tracker = Tracker()
        del tracker.issues["INC-4822"]
        sync(tmp_path, tracker, fields=["key"])
        tracker.issues["INC-4822"] = b'{"key": "INC-4822"}'

        report = sync(tmp_path, tracker, fields=["key"], hours=1)

        assert report.new == 1
        assert report.returned == ()
