"""R1.28 — a web page is followed through redirects only within the source's `url`.

A redirect is checked before it is followed, so a login form or another site is
never asked, and never stored as the page that was listed.
"""

from __future__ import annotations

import httpx
import pytest
from tests.docs_site import HTML, SITE, SITEMAP, URL, DocsSite, urlset

from dossier.infrastructure.connectors.web import WebConnector, WebRequestFailed

ESCALATION = f"{SITE}/ops/escalation"


def moved(to: str, status: int = 301) -> httpx.Response:
    return httpx.Response(status, headers={"Location": to})


class TestAWebPageRedirectsOnlyWithinItsSource:
    """R1.28 — inside `url`, five times at most."""

    def test_a_redirect_within_the_prefix_is_followed(self):
        """Example 1: the one where `escalation` moves to `escalation/`."""
        site = DocsSite(
            responses={
                ESCALATION: moved(f"{ESCALATION}/"),
                f"{ESCALATION}/": httpx.Response(
                    200, headers={"Content-Type": HTML}, content=b"<h1>Escalation</h1>"
                ),
            }
        )

        item = WebConnector(url=URL, transport=site.transport()).fetch("escalation")

        assert item.key == "escalation"
        assert item.payload == b"<h1>Escalation</h1>"

    def test_a_sixth_redirect_is_not_followed(self):
        """Example 2: the one where the chain within `/ops/` never ends."""
        hops = [f"{SITE}/ops/hop-{n}" for n in range(1, 7)]
        chain = [ESCALATION, *hops]
        site = DocsSite(
            responses={
                here: moved(there) for here, there in zip(chain, chain[1:], strict=False)
            }
        )
        connector = WebConnector(url=URL, transport=site.transport())

        with pytest.raises(WebRequestFailed) as raised:
            connector.fetch("escalation")

        assert ESCALATION in str(raised.value) and "5" in str(raised.value)
        page_requests = [url for url in site.urls_asked() if "/ops/" in url]
        assert page_requests == chain[:6]

    def test_a_redirect_to_a_login_page_fails_naming_both_urls(self):
        """Counter-example, row 3: the one where the page sends `dossier` to log in."""
        login = f"{SITE}/login?next=/ops/escalation"
        site = DocsSite(responses={ESCALATION: moved(login, 302)})
        connector = WebConnector(url=URL, transport=site.transport())

        with pytest.raises(WebRequestFailed) as raised:
            connector.fetch("escalation")

        assert ESCALATION in str(raised.value) and login in str(raised.value)
        assert login not in site.urls_asked()

    def test_a_sitemap_moving_to_https_on_its_host_is_followed(self):
        """Counter-example, row 4: the one where the sitemap moves from `http` to `https`."""
        plain = "http://docs.example.org/sitemap.xml"
        site = DocsSite(
            responses={
                plain: moved(SITEMAP),
                SITEMAP: httpx.Response(200, content=urlset({ESCALATION: None})),
            }
        )
        connector = WebConnector(url=URL, sitemap_url=plain, transport=site.transport())

        assert [ref.key for ref in connector.list(None)] == ["escalation"]
