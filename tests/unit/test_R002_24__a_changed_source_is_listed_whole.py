"""R2.24 — a change to a source's own keys makes its next listing complete, and
fetches nothing that did not change.

The keys a connector declares (R1.10) decide what a listing answers. After one
of them changes, an incremental listing answers a question about the source as
it was: `export: pdf` added to a synced Confluence source asked for no export,
taken away it tombstoned nothing, and a narrowed Jira query left the issues it
no longer matched `active`. So the hash of those keys is recorded, and a sync
that finds it changed lists without a window, as `--full` does (R2.22).

The source here is a stand-in that honours its window as a real server does --
a listing with `since` returns only what changed at or after it -- because a
stand-in that ignored the window is how R1.19 row 6 passed while false.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dossier.application.sync import SourceReport, sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.sync import State, listing_hash, sync_window
from dossier.infrastructure.ledger import LEDGER_PATH, Ledger
from dossier.infrastructure.store import SnapshotStore

SOURCE = "procedures-confluence"
EDITED = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
FIRST = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
SECOND = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
THIRD = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
DAY = timedelta(hours=24)


class Wiki:
    """Pages last edited on `EDITED`, each exported as `<page>.pdf` when asked to.

    `query` is a set of labels a page must carry, as a narrowed query would be.
    """

    lists_everything = False

    def __init__(self, *, export: bool, query: frozenset[str] = frozenset()) -> None:
        self.pages = {"81920114": {"procedure", "sev1"}, "81920115": {"procedure"}}
        self.export = export
        self.query = query
        self.asked: list[datetime | None] = []
        self.fetched: list[str] = []

    def list(self, since: datetime | None) -> Iterator[ItemRef]:
        self.asked.append(since)
        for key, labels in self.pages.items():
            if self.query <= labels and (since is None or since <= EDITED):
                yield ItemRef(key=key, remote_version="v37", updated_at=EDITED)

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        if self.export:
            yield AttachmentRef(key=f"{key}.pdf", item_key=key, remote_version="v37")

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        media = "application/pdf" if key.endswith(".pdf") else "text/markdown"
        return RawItem(
            key=key, payload=f"# {key}\n".encode(), media_type=media, remote_version="v37"
        )


def config(**options) -> SourceConfig:
    return SourceConfig(id=SOURCE, type="wiki", options={"url": "https://w.example", **options})


def sync(workspace: Path, source: SourceConfig, wiki: Wiki, *, now: datetime) -> SourceReport:
    with Ledger(workspace) as ledger:
        return sync_source(
            config=source,
            connector=wiki,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
        )


def state(workspace: Path, key: str) -> State | None:
    with Ledger(workspace) as ledger:
        row = ledger.row(SOURCE, key)
        return row.state if row else None


class TestAChangedSourceIsListedWhole:
    """R2.24 — the listing after a change answers today's keys."""

    def test_adding_export_lists_every_page_and_fetches_only_the_exports(self, tmp_path: Path):
        """Example 1: the one where `export: pdf` is added to a synced source."""
        sync(tmp_path, config(), Wiki(export=False), now=FIRST)
        wiki = Wiki(export=True)

        sync(tmp_path, config(export="pdf"), wiki, now=SECOND)

        assert wiki.asked == [None]
        assert sorted(wiki.fetched) == ["81920114.pdf", "81920115.pdf"]

    def test_taking_export_away_tombstones_every_export(self, tmp_path: Path):
        """Example 2: the one where the exports are no longer carried."""
        sync(tmp_path, config(export="pdf"), Wiki(export=True), now=FIRST)
        wiki = Wiki(export=False)

        report = sync(tmp_path, config(), wiki, now=SECOND)

        assert wiki.asked == [None]
        assert report.departed == ("81920114.pdf", "81920115.pdf")
        assert wiki.fetched == []

    def test_a_narrowed_query_tombstones_what_it_no_longer_matches(self, tmp_path: Path):
        """Example 3: the one where the query is narrowed to `sev1`."""
        sync(tmp_path, config(query="label = procedure"), Wiki(export=False), now=FIRST)
        narrowed = Wiki(export=False, query=frozenset({"sev1"}))

        report = sync(tmp_path, config(query="label = sev1"), narrowed, now=SECOND)

        assert narrowed.asked == [None]
        assert report.departed == ("81920115",)
        assert state(tmp_path, "81920115") is State.TOMBSTONED

    def test_the_sync_after_is_windowed_again(self, tmp_path: Path):
        """Example 4: the one where nothing changed since the complete listing."""
        sync(tmp_path, config(), Wiki(export=False), now=FIRST)
        sync(tmp_path, config(export="pdf"), Wiki(export=True), now=SECOND)
        wiki = Wiki(export=True)

        sync(tmp_path, config(export="pdf"), wiki, now=THIRD)

        assert wiki.asked == [SECOND - DAY]

    def test_a_wider_overlap_is_not_a_change_to_the_source(self, tmp_path: Path):
        """Counter-example, row 5: the one where only the window moves."""
        sync(tmp_path, config(), Wiki(export=False), now=FIRST)
        wiki = Wiki(export=False)
        wider = config().model_copy(update={"watermark_overlap": timedelta(hours=48)})

        sync(tmp_path, wider, wiki, now=SECOND)

        assert wiki.asked == [FIRST - 2 * DAY]

    def test_a_ledger_with_no_recorded_hash_is_listed_whole_once(self, tmp_path: Path):
        """Row 7: the one written before this rule existed."""
        sync(tmp_path, config(), Wiki(export=False), now=FIRST)
        with sqlite3.connect(tmp_path / LEDGER_PATH) as connection:
            connection.execute("DELETE FROM source_listing")
        once, then = Wiki(export=False), Wiki(export=False)

        sync(tmp_path, config(), once, now=SECOND)
        sync(tmp_path, config(), then, now=THIRD)

        assert once.asked == [None]
        assert then.asked == [SECOND - DAY]


class TestTheListingHash:
    """R2.24 — what the recorded hash is taken over, decided in the domain."""

    def test_it_is_the_sources_own_keys_in_any_order(self):
        one = SourceConfig(id=SOURCE, type="wiki", options={"url": "u", "query": "q"})
        other = SourceConfig(id=SOURCE, type="wiki", options={"query": "q", "url": "u"})

        assert listing_hash(one) == listing_hash(other)
        assert listing_hash(one) != listing_hash(config(export="pdf"))

    def test_the_core_keys_are_not_in_it(self):
        """Rows 5 and 6: `watermark_overlap` moves the window, `fields` is R2.3's."""
        plain = config()
        changed = plain.model_copy(
            update={"watermark_overlap": timedelta(hours=48), "fields": ["key", "fields"]}
        )

        assert listing_hash(plain) == listing_hash(changed)

    def test_a_changed_source_starts_from_nothing(self):
        """The window itself: `rescoped` asks what `full` asks (R2.22)."""
        assert (
            sync_window(reevaluating=False, last_sync_at=FIRST, overlap=DAY, rescoped=True)
            is None
        )
