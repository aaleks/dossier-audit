"""R1.38 — a crawl that cannot finish fails the listing, and lists nothing.

A crawl's listing is complete: a held page missing from it is tombstoned (R1.11,
R2.7). So a crawl that cannot tell it reached every page -- `url` is not a page,
a page answers `5xx`, `429` or nothing, redirects without end, or there is one
more URL to ask than `crawl:` allows -- fails, naming why, and returns nothing
it found on the way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from tests.docs_site import ROBOTS, ROBOTS_TXT, SITE, URL, DocsSite

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.sync import State
from dossier.infrastructure.connectors.web import WebConnector, WebRequestFailed
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

INDEX = f"{SITE}/ops/"
ESCALATION = f"{SITE}/ops/escalation"
MATRIX = f"{SITE}/ops/escalation-matrix.pdf"
SOURCE = SourceConfig(id="vendor-docs", type="web", options={"url": URL, "crawl": 50})


def vendor_docs(responses: dict[str, httpx.Response] | None = None) -> DocsSite:
    """`vendor-docs`, its `robots.txt` keeping `drafts/` out as the fixtures say."""
    robots = httpx.Response(200, text=ROBOTS_TXT)
    return DocsSite(responses={ROBOTS: robots, **(responses or {})})


def listing(site: DocsSite, crawl: int = 50) -> list[str]:
    connector = WebConnector(url=URL, crawl=crawl, transport=site.transport())
    return [ref.key for ref in connector.list(None)]


def failure(site: DocsSite, crawl: int = 50) -> str:
    with pytest.raises(WebRequestFailed) as raised:
        listing(site, crawl)
    return str(raised.value)


def held_then_crawled(site: DocsSite, workspace: Path) -> set[State]:
    """Every page held by a good crawl, then the states a failing crawl leaves them in."""
    good = vendor_docs()
    with Ledger(workspace) as ledger:
        sync_source(
            config=SOURCE,
            connector=WebConnector(url=URL, crawl=50, transport=good.transport()),
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
        )
    with Ledger(workspace) as ledger:
        with pytest.raises(WebRequestFailed):
            sync_source(
                config=SOURCE,
                connector=WebConnector(url=URL, crawl=50, transport=site.transport()),
                store=SnapshotStore(workspace),
                ledger=ledger,
                now=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
            )
        return {row.state for row in ledger.rows(SOURCE.id)}


def pages_asked(site: DocsSite) -> list[str]:
    return [url for url in site.urls_asked() if url != ROBOTS]


class TestACrawlThatCannotFinishFailsTheListing:
    """R1.38 — a crawl that cannot say it reached everything lists nothing."""

    def test_one_url_more_than_crawl_allows_fails_the_listing(self):
        """Example 1: the one where `crawl: 3` meets four pages."""
        site = vendor_docs()

        message = failure(site, crawl=3)

        assert "3" in message and MATRIX in message
        assert len(pages_asked(site)) == 3

    def test_a_page_answered_503_fails_the_listing(self, tmp_path: Path):
        """Example 2: the one where `escalation` is down, and nothing held is tombstoned."""
        site = vendor_docs({ESCALATION: httpx.Response(503)})

        message = failure(site)

        assert ESCALATION in message and "503" in message
        assert held_then_crawled(site, tmp_path) == {State.ACTIVE}

    def test_a_page_answered_429_fails_the_listing_and_nothing_more_is_asked(self):
        """Example 3: the one where the site says it is asked too often (R1.35)."""
        site = vendor_docs({ESCALATION: httpx.Response(429)})

        message = failure(site)

        assert ESCALATION in message and "429" in message
        assert pages_asked(site)[-1] == ESCALATION

    def test_a_page_that_does_not_answer_fails_the_listing(self):
        """Example 2's reason, for no answer at all."""
        site = vendor_docs()
        answering = site.transport()

        def silent(request: httpx.Request) -> httpx.Response:
            if str(request.url) == ESCALATION:
                raise httpx.ConnectTimeout("timed out", request=request)
            return answering.handle_request(request)

        connector = WebConnector(url=URL, crawl=50, transport=httpx.MockTransport(silent))
        with pytest.raises(WebRequestFailed) as raised:
            list(connector.list(None))

        assert ESCALATION in str(raised.value)

    def test_a_page_that_redirects_without_end_fails_the_listing(self):
        """Example 2's reason, for a redirect that never lands (R1.34)."""
        loop = httpx.Response(302, headers={"Location": ESCALATION})
        site = vendor_docs({ESCALATION: loop})

        message = failure(site)

        assert ESCALATION in message and "redirected more than" in message

    def test_a_url_that_is_not_a_page_fails_the_listing(self, tmp_path: Path):
        """Example 4: the one where `…/ops/` itself is gone."""
        site = vendor_docs({INDEX: httpx.Response(404)})

        message = failure(site)

        assert INDEX in message and "404" in message
        assert held_then_crawled(site, tmp_path) == {State.ACTIVE}

    def test_a_url_robots_txt_disallows_fails_the_listing(self):
        """Example 5: the one where the crawl may not start."""
        robots = httpx.Response(200, text=ROBOTS_TXT.replace("/ops/drafts/", "/ops/"))
        site = vendor_docs({ROBOTS: robots})

        message = failure(site)

        assert INDEX in message and "robots.txt" in message
        assert pages_asked(site) == []

    def test_a_crawl_that_asks_exactly_crawl_urls_has_finished(self):
        """Counter-example, row 6: the one where `crawl: 4` meets four pages."""
        site = vendor_docs()

        assert listing(site, crawl=4) == [
            "escalation",
            "escalation-matrix.pdf",
            "index",
            "runbooks/dns-failover.html",
        ]
