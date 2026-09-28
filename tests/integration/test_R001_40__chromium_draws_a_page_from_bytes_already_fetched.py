"""R1.40 — a real headless Chromium draws `vendor-docs`' shells.

The unit suite draws them with `tests.drawing.FakeBrowser`, which claims what
Chromium does. Here Chromium does it: it is handed what the site sent, runs the
real `/assets/app.js`, and every request it makes is answered by the connector
from `tests.docs_site`'s transport. Nothing reaches a network.

`live`, like every test that drives a browser: it needs `dossier[browser]` and
`playwright install chromium-headless-shell`, and takes a few seconds.
"""

from __future__ import annotations

import codecs
from collections import Counter

import httpx
import pytest
from tests.docs_site import ROBOTS, SITE, URL
from tests.drawing import API, APP, TEXT, drawn_site, html, shell

from dossier.infrastructure.connectors.browser import Answer, Chromium
from dossier.infrastructure.connectors.web import USER_AGENT, WebConnector, WebRequestFailed
from dossier.infrastructure.converters.html_markdown import HtmlMarkdownConverter

pytestmark = pytest.mark.live
pytest.importorskip("playwright", reason="needs dossier[browser]")

ESCALATION = f"{SITE}/ops/escalation"


def nowhere(asked) -> Answer:
    """Another host, which this test does not let the browser reach."""
    return Answer(status=404, headers={}, body=b"")


def chromium(timeout_seconds: float = 30) -> Chromium:
    return Chromium(user_agent=USER_AGENT, timeout_seconds=timeout_seconds, outside=nowhere)


def drawer(site, **options) -> WebConnector:
    return WebConnector(
        url=URL, render="browser", browser=chromium, transport=site.transport(), **options
    )


def note(payload: bytes) -> str:
    return HtmlMarkdownConverter().convert(payload, {}).decode("utf-8")


class TestChromiumDrawsAPageFromBytesAlreadyFetched:
    """R1.40 — the fake's claims, made good by a real browser."""

    def test_the_script_writes_the_page_and_the_page_is_asked_once(self):
        """Examples 1 and 2: the one where `app.js` really runs."""
        site = drawn_site(escalation=shell("/api/escalation"))

        item = drawer(site).fetch("escalation")

        assert b"<h1>Escalation</h1>" in item.payload
        written = note(item.payload)
        assert written.startswith("# Escalation\n") and TEXT in written
        asked = Counter(site.urls_asked())
        assert asked[ESCALATION] == 1 and asked[APP] == 1 and asked[API] == 1

    def test_a_crawl_follows_the_links_a_script_draws(self):
        """Example 3: the one where `index`'s menu exists only once drawn."""
        site = drawn_site(index=shell("/api/index"))
        site.responses[ROBOTS] = httpx.Response(
            200, text="User-agent: *\nDisallow: /ops/drafts/\n"
        )

        keys = [ref.key for ref in drawer(site, crawl=50).list(None)]

        assert keys == [
            "escalation",
            "escalation-matrix.pdf",
            "index",
            "runbooks/dns-failover.html",
        ]

    def test_a_drawn_page_is_held_in_utf8_behind_a_byte_order_mark(self):
        """Example 4: the one where a windows-1252 shell is drawn with UTF-8 text (R8.32)."""
        legacy = shell("/api/escalation", charset="windows-1252", extra="<p>Déclaré</p>")
        site = drawn_site()
        site.responses[ESCALATION] = html(legacy, charset="windows-1252")
        site.responses[API] = html("<p>Incident résolu.</p>")

        item = drawer(site).fetch("escalation")

        assert item.payload.startswith(codecs.BOM_UTF8)
        text = item.payload.decode("utf-8-sig")
        assert "Déclaré" in text and "résolu" in text
        written = note(item.payload)
        assert "Déclaré" in written and "résolu" in written

    def test_a_page_that_never_goes_quiet_fails(self):
        """Counter-example, row 7: the one where a script asks forever."""
        ping = f"{SITE}/api/ping"
        forever = "<script>setInterval(() => fetch('/api/ping'), 100);</script>"
        site = drawn_site(escalation=shell("/api/escalation", extra=forever))
        site.responses[ping] = html("pong")
        connector = WebConnector(
            url=URL,
            render="browser",
            browser=lambda: chromium(timeout_seconds=3),
            transport=site.transport(),
        )

        with pytest.raises(WebRequestFailed) as raised:
            connector.fetch("escalation")

        assert ESCALATION in str(raised.value) and "quiet" in str(raised.value)
