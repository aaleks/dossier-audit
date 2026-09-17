"""R1.4 — `list(since=t)` returns a superset of the items changed at or after `t`.

Returning extra items is correct and cheap: the next fetch compares version
markers and hashes, and an item that did not really change is a request rather
than a snapshot (R2.1, R2.2). Omitting one is a defect that presents as a
document silently going stale, with no error anywhere to see it by.

So the rule is one-sided, and the test is written that way: the claim is checked
as a contract against three connectors -- one that filters strictly, one that
filters not at all, and one whose bound is exclusive. The first two satisfy it
and disagree with each other about which extra items to return; the third
violates it, which is what gives the check teeth.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from dossier.domain.ports import ItemRef
from dossier.infrastructure.connectors.folder import FolderConnector

SINCE = datetime(2026, 8, 5, 9, 0, 0, tzinfo=UTC)

# `_fixtures.md`'s incidents, and when each last changed.
CHANGED_AT = {
    "INC-4821": datetime(2026, 7, 30, 9, 14, 0, tzinfo=UTC),
    "INC-4822": datetime(2026, 8, 5, 16, 2, 0, tzinfo=UTC),
    "INC-4901": SINCE,
}


class Filtering:
    """A tracker that answers `since` exactly, as a well-behaved Jira connector does."""

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(CHANGED_AT):
            if since is None or CHANGED_AT[key] >= since:
                yield ItemRef(key=key, remote_version="v1", updated_at=CHANGED_AT[key])


class Everything:
    """A tracker that ignores `since`. Wasteful, and entirely correct (R1.4)."""

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(CHANGED_AT):
            yield ItemRef(key=key, remote_version="v1", updated_at=CHANGED_AT[key])


class ExclusiveBound:
    """The defect this rule exists to name: `>` where the rule says `>=`."""

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(CHANGED_AT):
            if since is None or CHANGED_AT[key] > since:
                yield ItemRef(key=key, remote_version="v1", updated_at=CHANGED_AT[key])


def changed_at_or_after(since: datetime) -> set[str]:
    """What the source knows changed at or after `since` -- what a listing must cover."""
    return {key for key, changed in CHANGED_AT.items() if changed >= since}


def omitted_by(connector, since: datetime) -> set[str]:
    """Items the rule requires and this listing left out. Empty is the whole claim."""
    return changed_at_or_after(since) - {ref.key for ref in connector.list(since)}


class TestListSinceReturnsASuperset:
    """R1.4 — extra items are correct; a missing one is a defect."""

    def test_an_item_changed_after_since_is_in_the_result(self):
        """Example 1: the one where `INC-4822` changed at `2026-08-05T16:02:00Z`."""
        keys = [ref.key for ref in Filtering().list(SINCE)]

        assert "INC-4822" in keys
        assert omitted_by(Filtering(), SINCE) == set()

    def test_an_older_item_may_be_present_or_absent(self):
        """Example 2: the one where `INC-4821` changed on `2026-07-30`.

        Both answers are correct, and two conforming connectors disagree here.
        The rule constrains what a listing may *omit*, never what it may add --
        which is what lets a folder source answer at all (row 4).
        """
        filtered = [ref.key for ref in Filtering().list(SINCE)]
        everything = [ref.key for ref in Everything().list(SINCE)]

        assert "INC-4821" not in filtered
        assert "INC-4821" in everything
        assert omitted_by(Filtering(), SINCE) == omitted_by(Everything(), SINCE) == set()

    def test_an_item_changed_exactly_at_since_is_present(self):
        """Example 3: the one on the boundary, where `INC-4901` changed at `since`.

        Inclusive. An exclusive bound drops precisely the item that changed in
        the second the last sync recorded as its watermark, which is the item
        most likely to be missed and least likely to be noticed.
        """
        assert "INC-4901" in {ref.key for ref in Filtering().list(SINCE)}
        assert omitted_by(ExclusiveBound(), SINCE) == {"INC-4901"}

    def test_a_folder_source_returns_everything_regardless(self, tmp_path: Path):
        """Counter-example (row 4): the one with no change times to filter on.

        A folder has no per-item change time it can vouch for -- an mtime
        changes on copy and says nothing about content (R1.5 row 4). So it
        returns everything, which is always a legal answer to this rule.
        """
        for name in ("INC-4821.md", "INC-4822.md", "audit-note.pdf"):
            (tmp_path / name).write_bytes(b"held\n")

        everything = [ref.key for ref in FolderConnector(tmp_path).list(None)]
        since_recent = [ref.key for ref in FolderConnector(tmp_path).list(SINCE)]

        assert since_recent == everything
        assert all(ref.updated_at is None for ref in FolderConnector(tmp_path).list(SINCE))


class TestAServerZonedChangeTimeIsAskedFromAFloor:
    """R1.4, the one decision a connector was making itself: how much slack a server
    that compares change times in its own timezone needs."""

    def test_the_floor_is_a_day_before_since_whatever_the_offset(self):
        """The one where the server is fourteen hours from UTC and still answers a superset.

        No timezone is more than a day from UTC, so a day earlier is enough
        slack for any server, and the answer is a superset -- the one kind of
        error this rule permits.
        """
        from datetime import UTC, datetime, timedelta

        from dossier.domain.sync import server_zone_floor

        since = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)

        assert server_zone_floor(since) == datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
        assert server_zone_floor(since) <= since - timedelta(hours=14)
