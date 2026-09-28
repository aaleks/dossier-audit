"""R2.27 — a source whose listing fails is reported with the reason, and is left as
it was.

A listing that never finished is not complete, so nothing held is tombstoned;
the source's watermark, configuration hash and listing hash stay where the last
sync left them, and what it is owed stays owed. What it stored before the
listing failed stays stored. The report says why (`listing_failed`), and the
caller -- `dossier sync` -- goes on to the next source.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
from tests.docs_site import SITE, SITEMAP, URL, DocsSite

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.sync import State
from dossier.infrastructure.connectors.web import WebConnector
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

SOURCE = SourceConfig(id="vendor-docs", type="web", options={"url": URL})
FIRST = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
SECOND = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
UNREADABLE = httpx.Response(503)


def sync(workspace: Path, connector, *, now: datetime, config: SourceConfig = SOURCE):
    with Ledger(workspace) as ledger:
        return sync_source(
            config=config,
            connector=connector,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
        )


class HalfListed:
    """A listing that returns two items and then fails, as a server can mid-way."""

    lists_everything = True

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        yield ItemRef(key="OPS-114", remote_version="v37", updated_at=None)
        yield ItemRef(key="OPS-115", remote_version="v12", updated_at=None)
        raise ConnectionError("GET …/content/search?start=50 answered 502 Bad Gateway")

    def fetch(self, key: str) -> RawItem:
        return RawItem(
            key=key,
            payload=f"# {key}\n".encode(),
            media_type="text/markdown",
            remote_version="v1",
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


class TestAFailedListingLeavesItsSourceAsItWas:
    """R2.27 — a listing that never finished changes nothing it did not reach."""

    def test_the_report_says_why(self, tmp_path: Path):
        """Example 1: the one where the sitemap answers `503`."""
        site = DocsSite(responses={SITEMAP: UNREADABLE})

        report = sync(tmp_path, WebConnector(url=URL, transport=site.transport()), now=FIRST)

        assert report.listing_failed is not None
        assert SITEMAP in report.listing_failed and "503" in report.listing_failed

    def test_what_it_held_stays_active_and_its_marks_stay_put(self, tmp_path: Path):
        """Example 2: the one where the four pages outlive an unreadable sitemap."""
        site = DocsSite()
        sync(tmp_path, WebConnector(url=URL, transport=site.transport()), now=FIRST)
        with Ledger(tmp_path) as ledger:
            watermark = ledger.watermark(SOURCE.id)
            listed_under = ledger.listing_hash(SOURCE.id)
            configured = ledger.config_hash(SOURCE.id)
        site.responses[SITEMAP] = UNREADABLE

        report = sync(tmp_path, WebConnector(url=URL, transport=site.transport()), now=SECOND)

        assert report.tombstoned == 0
        with Ledger(tmp_path) as ledger:
            assert {row.state for row in ledger.rows(SOURCE.id)} == {State.ACTIVE}
            assert len(ledger.rows(SOURCE.id)) == 4
            assert ledger.watermark(SOURCE.id) == watermark
            assert ledger.listing_hash(SOURCE.id) == listed_under
            assert ledger.config_hash(SOURCE.id) == configured

    def test_what_it_is_owed_stays_owed(self, tmp_path: Path):
        """Example 3: the one where `escalation` failed before, and cannot be asked now."""
        escalation = f"{SITE}/ops/escalation"
        site = DocsSite(responses={escalation: httpx.Response(500)})
        sync(tmp_path, WebConnector(url=URL, transport=site.transport()), now=FIRST)
        site.responses = {SITEMAP: UNREADABLE}

        sync(tmp_path, WebConnector(url=URL, transport=site.transport()), now=SECOND)

        with Ledger(tmp_path) as ledger:
            assert [key for key, _ in ledger.owed(SOURCE.id)] == ["escalation"]

    def test_what_was_stored_before_the_failure_stays_stored(self, tmp_path: Path):
        """Example 4: the one where a listing fails on its second page."""
        config = SourceConfig(id="procedures-confluence", type="half", options={})

        report = sync(tmp_path, HalfListed(), now=FIRST, config=config)

        assert report.new == 2 and report.tombstoned == 0
        assert "502" in (report.listing_failed or "")
        with Ledger(tmp_path) as ledger:
            assert sorted(row.key for row in ledger.rows(config.id)) == ["OPS-114", "OPS-115"]

    def test_a_failed_fetch_is_not_a_failed_listing(self, tmp_path: Path):
        """Counter-example, row 6: the one R1.9 and R2.23 already describe."""
        site = DocsSite(responses={f"{SITE}/ops/escalation": httpx.Response(500)})

        report = sync(tmp_path, WebConnector(url=URL, transport=site.transport()), now=FIRST)

        assert report.listing_failed is None
        assert report.failed == ("escalation",) and report.new == 3
