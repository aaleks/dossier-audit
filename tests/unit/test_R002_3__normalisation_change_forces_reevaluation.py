"""R2.3 — changing the normalisation field list re-evaluates every item in that source.

The projection is part of the source's configuration hash, because a different
projection means the recorded hashes answer a different question. An item whose
version marker never moved still has to be fetched again: the source has nothing
to say about a question dossier has only just started asking.

Rows 2 and 4 are claims about the hash itself. Rows 1 and 3 are claims about what
a second sync does, so they are measured through `sync_source` over a real ledger
and store, against a tracker that vouches -- correctly -- that nothing moved.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dossier.application.sync import SourceReport, sync_source
from dossier.domain.ledger import LedgerRow
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.sync import source_config_hash
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

FIRST = datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC)
LATER = FIRST + timedelta(days=1)

ISSUES = {
    "INC-4821": {
        "key": "INC-4821",
        "summary": "Batch failed",
        "description": "Loss of CHF 48'200 on page 3.",
        "comments": ["reviewed by risk"],
    },
    "INC-4822": {
        "key": "INC-4822",
        "summary": "Settlement mismatch",
        "description": "Reconciled the following morning.",
        "comments": [],
    },
}


def source(fields: list[str] | None, *, overlap: str | None = None) -> SourceConfig:
    declared = {"id": "incidents-jira", "type": "jira", "fields": fields}
    if overlap is not None:
        declared["watermark_overlap"] = overlap
    return SourceConfig(**declared)


class IssueTracker:
    """Issues at version markers it vouches for. It counts what it is asked to fetch."""

    lists_everything = False

    media_type = "application/json"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(ISSUES):
            yield ItemRef(key=key, remote_version="v1", updated_at=None)

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        return RawItem(
            key=key,
            payload=json.dumps(ISSUES[key]).encode(),
            media_type=self.media_type,
            remote_version="v1",
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


def sync(
    workspace: Path, tracker: IssueTracker, config: SourceConfig, *, now: datetime
) -> SourceReport:
    with Ledger(workspace) as ledger:
        return sync_source(
            config=config,
            connector=tracker,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
        )


def rows(workspace: Path) -> list[LedgerRow]:
    with Ledger(workspace) as ledger:
        return ledger.rows("incidents-jira")


def hashes(workspace: Path) -> dict[str, str]:
    return {row.key: row.content_hash for row in rows(workspace)}


@pytest.fixture
def held(tmp_path: Path) -> IssueTracker:
    """Both issues synced once under `fields: [key, summary, description]`."""
    tracker = IssueTracker()
    sync(tmp_path, tracker, source(["key", "summary", "description"]), now=FIRST)
    tracker.fetched.clear()
    return tracker


class TestNormalisationChangeForcesReevaluation:
    """R2.3 — a changed projection re-evaluates every item in that source."""

    def test_gaining_a_field_refetches_and_rehashes_every_item(
        self, tmp_path: Path, held: IssueTracker
    ):
        """Example 1: the one where `fields` gains `comments`.

        Every item is fetched again although the tracker still reports `v1` for
        both, and both are re-hashed: the recorded hashes answered a question
        about three fields, and the question now has four.
        """
        before = hashes(tmp_path)
        widened = source(["key", "summary", "description", "comments"])

        assert source_config_hash(widened) != source_config_hash(
            source(["key", "summary", "description"])
        )

        sync(tmp_path, held, widened, now=LATER)

        assert held.fetched == sorted(ISSUES)
        assert hashes(tmp_path) != before

    def test_reordering_the_fields_changes_nothing(self, tmp_path: Path, held: IssueTracker):
        """Example 2: the one reordered from `[key, summary]` to `[summary, key]`.

        The projection is a set, ordered canonically before hashing. A source
        whose author moved a line is the same source, and re-fetching a corpus
        because of it would be a day's work for a diff nobody made.
        """
        assert source_config_hash(source(["key", "summary"])) == source_config_hash(
            source(["summary", "key"])
        )

        sync(tmp_path, held, source(["key", "summary", "description"]), now=LATER)
        reordered = source(["description", "key", "summary"])
        held.fetched.clear()

        sync(tmp_path, held, reordered, now=LATER)

        assert held.fetched == []

    def test_losing_a_field_refetches_every_item(self, tmp_path: Path, held: IssueTracker):
        """Example 3: the one where `fields` loses `description`.

        Narrowing is as much a change as widening: the recorded hashes cover a
        field the source no longer projects onto, so none of them answers the
        question being asked now.
        """
        narrowed = source(["key", "summary"])

        assert source_config_hash(narrowed) != source_config_hash(
            source(["key", "summary", "description"])
        )

        sync(tmp_path, held, narrowed, now=LATER)

        assert held.fetched == sorted(ISSUES)

    def test_changing_the_overlap_is_not_a_projection_change(
        self, tmp_path: Path, held: IssueTracker
    ):
        """Counter-example (row 4): the one where `watermark_overlap` goes `24h` -> `48h`.

        No configuration hash change, and nothing re-fetched. The overlap decides
        what is asked for, never what a payload hashes to (R2.4).
        """
        fields = ["key", "summary", "description"]

        assert source_config_hash(source(fields, overlap="24h")) == source_config_hash(
            source(fields, overlap="48h")
        )

        sync(tmp_path, held, source(fields, overlap="48h"), now=LATER)

        assert held.fetched == []

    def test_a_source_that_declares_no_fields_has_a_hash_of_its_own(self, tmp_path: Path):
        """The boundary between "no projection" and any projection at all.

        A source with no `fields` hashes its payload as received (R2.10). That is
        a different question from every projection, including one naming every
        field a payload happens to have, so it hashes differently.
        """
        every_field = source(["key", "summary", "description", "comments"])

        assert source_config_hash(source(None)) != source_config_hash(every_field)


class TestWhatAChangedProjectionDecides:
    """R2.3 at the decision: the three predicates the use case orders.

    Each is one line with two inputs, proved here with two strings and a bool
    rather than by driving `sync_source` over a connector, a store and a ledger.
    """

    def test_a_recorded_hash_that_differs_is_a_changed_projection(self):
        """Row 1's trigger: the one where the projection moved since the hashing."""
        from dossier.domain.sync import projection_changed

        assert projection_changed(recorded="a3f9c1e2" * 8, configured="77c1b40a" * 8) is True
        assert projection_changed(recorded="a3f9c1e2" * 8, configured="a3f9c1e2" * 8) is False

    def test_a_source_that_never_synced_has_no_projection_to_change(self):
        """Counter-example: the one with nothing recorded; a first sync fetches everything."""
        from dossier.domain.sync import projection_changed

        assert projection_changed(recorded=None, configured="a3f9c1e2" * 8) is False

    def test_a_re_evaluation_lists_everything_and_a_normal_sync_lists_the_window(self):
        """The one where an incremental listing would omit the very rows to re-hash."""
        from dossier.domain.sync import sync_window

        watermark = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)

        assert (
            sync_window(reevaluating=True, last_sync_at=watermark, overlap=timedelta(hours=24))
            is None
        )
        assert sync_window(
            reevaluating=False, last_sync_at=watermark, overlap=timedelta(hours=24)
        ) == datetime(2026, 8, 5, 9, 0, tzinfo=UTC)

    def test_a_changed_projection_refetches_items_and_not_their_attachments(self):
        """The one where an attachment hashes its own bytes, which no projection touches."""
        from dossier.domain.sync import must_refetch

        assert must_refetch(reevaluating=True, is_item=True) is True
        assert must_refetch(reevaluating=True, is_item=False) is False
        assert must_refetch(reevaluating=False, is_item=True) is False
