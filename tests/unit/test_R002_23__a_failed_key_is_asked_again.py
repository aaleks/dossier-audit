"""R2.23 — a key whose fetch failed is asked again at the next sync, whether or not
the listing returns its item.

R2.8 holds the watermark back when an item fails, so the next window starts
where the failed sync's did. That returns the item only if it changed inside the
window. A file that failed while its item stood still -- a Confluence export
refused under `--full`, a Jira attachment that timed out -- was never asked about
again, and the next sync moved the watermark past it without a word. So the
ledger remembers what it is owed, and sync visits an owed key's item whatever
the listing says.

The source is a stand-in honouring its window as a real server does: nothing
here was edited after `EDITED`, so a windowed listing returns nothing at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from dossier.application.sync import SourceReport, sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.sync import State, owed_items
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

SOURCE = SourceConfig(id="procedures-confluence", type="wiki", options={"export": "pdf"})
PAGE = "81920114"
EXPORT = f"{PAGE}.pdf"
EDITED = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
FIRST = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
SECOND = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
THIRD = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)


class Refused(RuntimeError):
    pass


class Wiki:
    """One page, its export, and whatever the test says goes wrong."""

    lists_everything = False

    def __init__(self, *, refuse: frozenset[str] = frozenset(), pages=(PAGE,), files=(EXPORT,)):
        self.refuse = refuse
        self.pages = pages
        self.files = files
        self.fetched: list[str] = []

    def list(self, since: datetime | None) -> Iterator[ItemRef]:
        for page in self.pages:
            if since is None or since <= EDITED:
                yield ItemRef(key=page, remote_version="v37", updated_at=EDITED)

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        for name in self.files:
            yield AttachmentRef(key=name, item_key=key, remote_version="v37")

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        if key in self.refuse:
            raise Refused(f"GET …?pageId={PAGE} answered 403 Forbidden")
        return RawItem(
            key=key,
            payload=f"%PDF-1.5 {key}".encode(),
            media_type="application/pdf",
            remote_version="v37",
        )


def sync(workspace: Path, wiki: Wiki, *, now: datetime, full: bool = False) -> SourceReport:
    with Ledger(workspace) as ledger:
        return sync_source(
            config=SOURCE,
            connector=wiki,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
            full=full,
        )


def watermark(workspace: Path) -> datetime | None:
    with Ledger(workspace) as ledger:
        return ledger.watermark(SOURCE.id)


class TestAFailedKeyIsAskedAgain:
    """R2.23 — what failed is owed, and asked for until it is settled."""

    def test_a_refused_export_is_asked_again_when_the_window_returns_nothing(self, tmp_path):
        """Example 1: the one where `--full` found the refusal and a plain sync followed."""
        sync(tmp_path, Wiki(files=()), now=FIRST)  # the page held, the watermark set
        refused = Wiki(refuse=frozenset({EXPORT}))
        sync(tmp_path, refused, now=SECOND, full=True)
        again = Wiki(refuse=frozenset({EXPORT}))

        report = sync(tmp_path, again, now=THIRD)

        assert again.fetched == [EXPORT]
        assert [key for key, _ in report.failures] == [EXPORT]
        assert watermark(tmp_path) == FIRST

    def test_an_export_that_succeeds_on_the_retry_is_not_asked_for_again(self, tmp_path):
        """Example 2: the one where the permission was granted in between."""
        sync(tmp_path, Wiki(refuse=frozenset({EXPORT})), now=FIRST)
        granted = Wiki()
        sync(tmp_path, granted, now=SECOND)
        quiet = Wiki()

        sync(tmp_path, quiet, now=THIRD)

        assert EXPORT in granted.fetched
        assert quiet.fetched == []
        with Ledger(tmp_path) as ledger:
            assert ledger.row(SOURCE.id, EXPORT).state is State.ACTIVE

    def test_the_item_is_not_fetched_again_for_its_files_sake(self, tmp_path):
        """Example 3: the one where only the file failed, and the item stood still."""
        sync(tmp_path, Wiki(files=()), now=FIRST)
        sync(tmp_path, Wiki(refuse=frozenset({EXPORT})), now=SECOND, full=True)
        again = Wiki()

        sync(tmp_path, again, now=THIRD)

        assert again.fetched == [EXPORT]

    def test_a_file_no_longer_carried_is_owed_nothing(self, tmp_path):
        """Counter-example, row 4: the one where the export was taken off the page."""
        sync(tmp_path, Wiki(refuse=frozenset({EXPORT})), now=FIRST)
        without = Wiki(files=())
        sync(tmp_path, without, now=SECOND)
        after = Wiki(files=())

        report = sync(tmp_path, after, now=THIRD)

        assert without.fetched == [] and after.fetched == []
        assert report.failures == ()
        with Ledger(tmp_path) as ledger:
            assert ledger.row(SOURCE.id, EXPORT) is None
            assert ledger.owed(SOURCE.id) == []

    def test_an_owed_item_a_complete_listing_drops_is_not_asked(self, tmp_path):
        """Counter-example, row 5: the one where the page itself is gone."""
        sync(tmp_path, Wiki(files=()), now=FIRST)
        sync(tmp_path, Wiki(refuse=frozenset({EXPORT})), now=SECOND, full=True)
        gone = Wiki(pages=())

        report = sync(tmp_path, gone, now=THIRD, full=True)

        assert gone.fetched == []
        assert PAGE in report.departed
        with Ledger(tmp_path) as ledger:
            assert ledger.owed(SOURCE.id) == []


class TestWhichItemsAreVisited:
    """R2.23 — the decision over the owed keys and the listing, made in the domain."""

    def test_an_owed_file_visits_its_item_without_fetching_it(self):
        assert owed_items([(EXPORT, PAGE)], visited=set(), complete=False) == [(PAGE, False)]

    def test_an_owed_item_is_fetched(self):
        assert owed_items([(PAGE, None)], visited=set(), complete=False) == [(PAGE, True)]

    def test_an_item_the_listing_returned_is_not_visited_twice(self):
        assert owed_items([(EXPORT, PAGE)], visited={PAGE}, complete=False) == []

    def test_a_complete_listing_answers_for_every_item(self):
        """What it did not return is gone, and is tombstoned rather than asked (R2.7)."""
        assert (
            owed_items([(EXPORT, PAGE), ("81920115", None)], visited=set(), complete=True) == []
        )
