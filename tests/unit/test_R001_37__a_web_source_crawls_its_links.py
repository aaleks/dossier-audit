"""R1.37 — with `crawl:`, a web source lists every page its links reach within its
`url`, and reads no sitemap.

`www.python.org` publishes no sitemap, and its listing failed on the `404`. A
source that says `crawl:` starts at `url` and follows the `<a href>`s of each
HTML page that lie under it, asking each URL once. A page is keyed by the URL
it was answered at; a link that is not a page -- a `404`, a redirect out of
`url` -- is left out, and the crawl goes on. `fetch` hands back what the crawl
was answered, so a page is asked once a sync.

Every request goes through `tests.docs_site`, whose pages link one another as
`specs/_fixtures.md` says. No socket is opened.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
from tests.docs_site import ROBOTS, ROBOTS_TXT, SITE, SITEMAP, URL, DocsSite

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.infrastructure.connectors.web import WebConnector
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

INDEX = f"{SITE}/ops/"
ESCALATION = f"{SITE}/ops/escalation"
FAILOVER = f"{SITE}/ops/runbooks/dns-failover.html"
MATRIX = f"{SITE}/ops/escalation-matrix.pdf"
PAGES = [INDEX, ESCALATION, FAILOVER, MATRIX]
SOURCE = SourceConfig(id="vendor-docs", type="web", options={"url": URL, "crawl": 50})


def vendor_docs(responses: dict[str, httpx.Response] | None = None) -> DocsSite:
    """`vendor-docs`, its `robots.txt` keeping `drafts/` out as the fixtures say."""
    robots = httpx.Response(200, text=ROBOTS_TXT)
    return DocsSite(responses={ROBOTS: robots, **(responses or {})})


def crawler(site: DocsSite) -> WebConnector:
    return WebConnector(url=URL, crawl=50, transport=site.transport())


def keys(site: DocsSite) -> list[str]:
    return [ref.key for ref in crawler(site).list(None)]


def sync(site: DocsSite, workspace: Path, day: int):
    with Ledger(workspace) as ledger:
        return sync_source(
            config=SOURCE,
            connector=crawler(site),
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=datetime(2026, 8, day, 9, 0, tzinfo=UTC),
        )


def pages_asked(site: DocsSite) -> Counter[str]:
    return Counter(url for url in site.urls_asked() if url != ROBOTS)


class TestAWebSourceCrawlsItsLinks:
    """R1.37 — the pages reachable from `url` by links within it are the listing."""

    def test_the_pages_its_links_reach_are_listed_and_no_sitemap_is_read(self):
        """Example 1: the one where `vendor-docs` is listed by following its links."""
        site = vendor_docs()

        assert keys(site) == [
            "escalation",
            "escalation-matrix.pdf",
            "index",
            "runbooks/dns-failover.html",
        ]
        assert SITEMAP not in site.urls_asked()
        assert f"{SITE}/blog/release-notes" not in site.urls_asked()

    def test_a_sync_asks_each_page_once(self, tmp_path: Path):
        """Example 2: the one where `fetch` hands back what the crawl was answered."""
        site = vendor_docs()

        report = sync(site, tmp_path, day=6)

        assert report.new == 4 and report.failed == ()
        assert pages_asked(site) == Counter(dict.fromkeys(PAGES, 1))

    def test_a_second_sync_asks_again_and_stores_nothing_unchanged(self, tmp_path: Path):
        """Example 3: the one where a crawled page has no marker, and its bytes decide."""
        site = vendor_docs()
        sync(site, tmp_path, day=6)

        report = sync(site, tmp_path, day=7)

        assert report.snapshots_written == 0 and report.known == 4
        assert pages_asked(site) == Counter(dict.fromkeys(PAGES, 2))

    def test_one_page_linked_three_ways_is_asked_once(self):
        """Example 4: the one where a fragment and the host's case are not addresses."""
        site = vendor_docs()
        site.links[INDEX] += ["escalation#paging", "https://DOCS.example.org/ops/escalation"]

        assert keys(site).count("escalation") == 1
        assert pages_asked(site)[ESCALATION] == 1
        assert "https://DOCS.example.org/ops/escalation" not in site.urls_asked()

    def test_a_page_is_keyed_by_the_url_it_was_answered_at(self):
        """Example 5: the one where `escalation` redirects to `escalation/`."""
        moved = f"{ESCALATION}/"
        site = vendor_docs({ESCALATION: httpx.Response(301, headers={"Location": moved})})
        site.pages[moved] = None
        site.links[moved] = ["../"]
        site.links[FAILOVER] = ["../escalation/"]

        listed = keys(site)

        assert "escalation/index" in listed and "escalation" not in listed
        assert pages_asked(site)[moved] == 1

    def test_a_link_is_read_against_the_pages_base(self):
        """Example 6: the one where `<base>` says where the page's links start."""
        body = (
            '<html><head><base href="https://docs.example.org/ops/runbooks/"></head>'
            '<body><a href="dns-failover.html">DNS failover</a></body></html>'
        )
        html = httpx.Response(200, headers={"Content-Type": "text/html"}, content=body)
        site = vendor_docs({INDEX: html})

        assert keys(site) == ["escalation", "index", "runbooks/dns-failover.html"]
        assert f"{SITE}/ops/dns-failover.html" not in site.urls_asked()

    def test_a_pdf_is_listed_and_not_read_for_links(self):
        """Counter-example, row 7: the one where only HTML is read for links."""
        pdf = httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=b'%PDF-1.7\n<a href="hidden">',
        )
        site = vendor_docs({MATRIX: pdf})

        assert "escalation-matrix.pdf" in keys(site)
        assert f"{SITE}/ops/hidden" not in site.urls_asked()

    def test_a_link_answered_404_is_not_a_page(self):
        """Counter-example, row 8: the one where a site's broken link is not its page."""
        site = vendor_docs()
        site.links[INDEX].append("old-runbook")

        assert keys(site) == [
            "escalation",
            "escalation-matrix.pdf",
            "index",
            "runbooks/dns-failover.html",
        ]
        assert f"{SITE}/ops/old-runbook" in site.urls_asked()

    def test_a_link_that_leaves_the_source_is_not_a_page(self):
        """Counter-example, row 9: the one where `login` sends `dossier` to a sign-in."""
        login = f"{SITE}/ops/login"
        site = vendor_docs(
            {login: httpx.Response(302, headers={"Location": "https://sso.example.org/login"})}
        )
        site.links[INDEX].append("login")

        assert "login" not in keys(site)
        assert not any("sso.example.org" in url for url in site.urls_asked())

    def test_a_link_robots_txt_disallows_is_neither_asked_nor_listed(self):
        """Counter-example, row 10: the one where `drafts/` is kept out (R1.33)."""
        site = vendor_docs()
        draft = f"{SITE}/ops/drafts/escalation-v2"
        site.pages[draft] = None

        assert "Disallow: /ops/drafts/" in ROBOTS_TXT
        assert "drafts/escalation-v2" not in keys(site)
        assert draft not in site.urls_asked()

    def test_a_link_with_a_query_is_not_asked(self):
        """Counter-example, row 11: the one where a query is one page served another way."""
        site = vendor_docs()
        site.links[INDEX].append("escalation?print=1")

        keys(site)

        assert f"{ESCALATION}?print=1" not in site.urls_asked()
