"""R1.29 — a web source lists every URL its sitemap names under its `url`, and nothing else.

A sitemap index is followed to each sitemap it names on the same host. A sitemap
that cannot be read fails the listing: the listing is complete, and an empty one
would tombstone every page held (R1.11, R2.7).

Every request goes through `tests.docs_site`, an `httpx.MockTransport` playing
`https://docs.example.org`. No socket is opened.
"""

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from tests.docs_site import SITE, SITEMAP, URL, DocsSite, sitemapindex, urlset

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.sync import State
from dossier.infrastructure.connectors.web import WebConnector, WebRequestFailed
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

SINCE = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)


def keys(site: DocsSite) -> list[str]:
    connector = WebConnector(url=URL, transport=site.transport())
    return [ref.key for ref in connector.list(None)]


class TestAWebSourceListsWhatItsSitemapNames:
    """R1.29 — the sitemap under `url` is the listing."""

    def test_every_page_under_the_prefix_is_listed_sorted_by_key(self):
        """Example 1: the one where `vendor-docs` lists its pages from its sitemap."""
        site = DocsSite(
            pages={
                f"{SITE}/ops/escalation": None,
                f"{SITE}/ops/runbooks/dns-failover.html": None,
                f"{SITE}/ops/": None,
            }
        )

        assert keys(site) == ["escalation", "index", "runbooks/dns-failover.html"]

    def test_a_sitemap_index_is_followed_to_every_sitemap_it_names(self):
        """Example 2: the one where the pages are spread over two sitemaps."""
        ops, blog = f"{SITE}/sitemap-ops.xml", f"{SITE}/sitemap-blog.xml"
        site = DocsSite(
            responses={
                SITEMAP: httpx.Response(200, content=sitemapindex([ops, blog])),
                ops: httpx.Response(200, content=urlset({f"{SITE}/ops/escalation": None})),
                blog: httpx.Response(
                    200,
                    content=urlset({f"{SITE}/blog/release-notes": None, f"{SITE}/ops/": None}),
                ),
            }
        )

        assert keys(site) == ["escalation", "index"]
        assert ops in site.urls_asked() and blog in site.urls_asked()

    def test_a_compressed_sitemap_is_read_as_if_it_were_not(self):
        """Example 3: the one where the sitemap is `sitemap.xml.gz`."""
        compressed = f"{SITE}/sitemap.xml.gz"
        site = DocsSite(
            responses={
                compressed: httpx.Response(
                    200,
                    headers={"Content-Type": "application/gzip"},
                    content=gzip.compress(urlset({f"{SITE}/ops/escalation": None})),
                )
            }
        )
        connector = WebConnector(url=URL, sitemap_url=compressed, transport=site.transport())

        assert [ref.key for ref in connector.list(None)] == ["escalation"]

    def test_the_listing_is_complete_whatever_since_is_asked(self):
        """Example 4: the one where `since` narrows nothing."""
        site = DocsSite()
        connector = WebConnector(url=URL, transport=site.transport())

        assert connector.lists_everything is True
        assert list(connector.list(SINCE)) == list(connector.list(None))

    def test_a_page_gone_from_the_sitemap_is_tombstoned_at_the_next_sync(self, tmp_path: Path):
        """Example 4: the one where `escalation` leaves the sitemap."""
        config = SourceConfig(id="vendor-docs", type="web", options={"url": URL})
        site = DocsSite()

        def sync(now: datetime):
            with Ledger(tmp_path) as ledger:
                return sync_source(
                    config=config,
                    connector=WebConnector(url=URL, transport=site.transport()),
                    store=SnapshotStore(tmp_path),
                    ledger=ledger,
                    now=now,
                )

        sync(datetime(2026, 8, 6, 9, 0, tzinfo=UTC))
        del site.pages[f"{SITE}/ops/escalation"]
        report = sync(datetime(2026, 8, 7, 9, 0, tzinfo=UTC))

        assert report.departed == ("escalation",)
        with Ledger(tmp_path) as ledger:
            assert ledger.row(config.id, "escalation").state is State.TOMBSTONED
            assert ledger.row(config.id, "index").state is State.ACTIVE

    def test_a_url_outside_the_prefix_on_another_host_or_with_a_query_is_not_listed(self):
        """Counter-example, row 5: the one where the sitemap names more than it covers."""
        site = DocsSite(
            pages={
                f"{SITE}/ops/escalation": None,
                f"{SITE}/blog/release-notes": None,
                "https://other.example.net/ops/escalation": None,
                f"{SITE}/ops/escalation?lang=de": None,
            }
        )

        assert keys(site) == ["escalation"]

    def test_a_sitemap_that_cannot_be_read_fails_the_listing(self, tmp_path: Path):
        """Counter-example, row 6: the one where the sitemap answers `404`."""
        config = SourceConfig(id="vendor-docs", type="web", options={"url": URL})
        site = DocsSite()
        with Ledger(tmp_path) as ledger:
            sync_source(
                config=config,
                connector=WebConnector(url=URL, transport=site.transport()),
                store=SnapshotStore(tmp_path),
                ledger=ledger,
                now=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
            )
        site.responses[SITEMAP] = httpx.Response(404)
        connector = WebConnector(url=URL, transport=site.transport())

        with pytest.raises(WebRequestFailed) as raised:
            list(connector.list(None))

        assert SITEMAP in str(raised.value) and "404" in str(raised.value)
        with Ledger(tmp_path) as ledger:
            assert {row.state for row in ledger.rows(config.id)} == {State.ACTIVE}

    def test_a_page_of_html_where_the_sitemap_should_be_fails_the_listing(self):
        """Counter-example, row 6: the one where the sitemap URL serves a 404 page."""
        site = DocsSite(
            responses={
                SITEMAP: httpx.Response(200, content=b"<html><body>Not here</body></html>")
            }
        )
        connector = WebConnector(url=URL, transport=site.transport())

        with pytest.raises(WebRequestFailed, match="not a sitemap"):
            list(connector.list(None))

    def test_an_index_naming_a_sitemap_on_another_host_does_not_read_it(self):
        """Counter-example, row 7: the one where the index points off the site."""
        elsewhere = "https://other.example.net/sitemap.xml"
        site = DocsSite(
            responses={SITEMAP: httpx.Response(200, content=sitemapindex([elsewhere]))}
        )

        assert keys(site) == []
        assert elsewhere not in site.urls_asked()
