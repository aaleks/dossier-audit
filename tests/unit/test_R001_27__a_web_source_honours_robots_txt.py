"""R1.27 — a URL the host's `robots.txt` disallows for `dossier` is neither listed nor fetched.

Read with protego, as RFC 9309 reads it. An absent `robots.txt` allows
everything; an unreadable one fails the listing rather than empty it, because
an empty complete listing tombstones every page held (R2.7).
"""

from __future__ import annotations

import httpx
import pytest
from tests.docs_site import PAGES, ROBOTS, SITE, URL, DocsSite

from dossier.infrastructure.connectors.web import WebConnector, WebRequestFailed

DRAFT = f"{SITE}/ops/drafts/escalation-v2"


def site_with(robots: httpx.Response) -> DocsSite:
    return DocsSite(pages={**PAGES, DRAFT: "2026-08-06"}, responses={ROBOTS: robots})


def keys(site: DocsSite) -> list[str]:
    return [ref.key for ref in WebConnector(url=URL, transport=site.transport()).list(None)]


class TestAWebSourceHonoursRobotsTxt:
    """R1.27 — what the site asks not to be read is not read."""

    def test_a_disallowed_directory_is_not_listed(self):
        """Example 1: the one where `/ops/drafts/` is disallowed for everyone."""
        site = site_with(httpx.Response(200, text="User-agent: *\nDisallow: /ops/drafts/\n"))

        assert keys(site) == [
            "escalation",
            "escalation-matrix.pdf",
            "index",
            "runbooks/dns-failover.html",
        ]

    def test_a_disallowed_page_is_not_fetched(self):
        """Example 2: the one where `drafts/escalation-v2` is asked for anyway."""
        site = site_with(httpx.Response(200, text="User-agent: *\nDisallow: /ops/drafts/\n"))
        connector = WebConnector(url=URL, transport=site.transport())

        with pytest.raises(WebRequestFailed) as raised:
            connector.fetch("drafts/escalation-v2")

        assert DRAFT in str(raised.value) and "robots.txt" in str(raised.value)
        assert DRAFT not in site.urls_asked()

    def test_a_wildcard_for_dossier_alone_is_read_as_rfc_9309_reads_it(self):
        """Example 3: the one where `Disallow: /*.pdf$` is for `dossier` only."""
        site = site_with(
            httpx.Response(
                200,
                text="User-agent: dossier\nDisallow: /*.pdf$\n\nUser-agent: *\nAllow: /\n",
            )
        )

        listed = keys(site)

        assert "escalation-matrix.pdf" not in listed
        assert "escalation" in listed and "drafts/escalation-v2" in listed

    def test_an_absent_robots_txt_allows_everything(self):
        """Counter-example, row 4: the one where `robots.txt` answers `404`."""
        assert "drafts/escalation-v2" in keys(site_with(httpx.Response(404)))

    def test_an_unreadable_robots_txt_fails_the_listing(self):
        """Counter-example, row 5: the one where `robots.txt` answers `503`."""
        connector = WebConnector(url=URL, transport=site_with(httpx.Response(503)).transport())

        with pytest.raises(WebRequestFailed) as raised:
            list(connector.list(None))

        assert ROBOTS in str(raised.value) and "503" in str(raised.value)
