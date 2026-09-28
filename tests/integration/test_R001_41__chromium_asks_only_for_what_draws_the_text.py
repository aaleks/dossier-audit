"""R1.41 — what a real headless Chromium asks for while it draws a page.

The unit suite's `FakeBrowser` claims which requests Chromium makes, and in what
order. Here Chromium makes them, running the real `/assets/app.js`: every one
comes back to the connector, which answers it from `tests.docs_site`'s transport,
leaves it to the browser, or refuses it. What the browser would send to another
host is answered here, and recorded, so nothing reaches a network.

`live`: it needs `dossier[browser]` and its Chromium.
"""

from __future__ import annotations

from collections import Counter

import httpx
import pytest
from tests.docs_site import ROBOTS, SITE, URL
from tests.drawing import API, APP, APP_JS, DIAGRAM, TEXT, drawn_site, shell

from dossier.infrastructure.connectors.browser import Answer, Asked, Chromium
from dossier.infrastructure.connectors.web import USER_AGENT, WebConnector, WebRequestFailed
from dossier.infrastructure.converters.html_markdown import HtmlMarkdownConverter

pytestmark = pytest.mark.live
pytest.importorskip("playwright", reason="needs dossier[browser]")

CDN = "https://cdn.example.net/app.js"


class Elsewhere:
    """Every host but the site's, as far as the browser can tell: recorded, and answered."""

    def __init__(self) -> None:
        self.sent: list[Asked] = []

    def __call__(self, asked: Asked) -> Answer:
        self.sent.append(asked)
        if asked.url == CDN:
            return Answer(
                status=200, headers={"Content-Type": "text/javascript"}, body=APP_JS.encode()
            )
        return Answer(status=404, headers={}, body=b"")


def drawer(site, elsewhere: Elsewhere, **options) -> WebConnector:
    return WebConnector(
        url=URL,
        render="browser",
        browser=lambda: Chromium(user_agent=USER_AGENT, timeout_seconds=30, outside=elsewhere),
        transport=site.transport(),
        **options,
    )


def note(payload: bytes) -> str:
    return HtmlMarkdownConverter().convert(payload, {}).decode("utf-8")


class TestChromiumAsksOnlyForWhatDrawsTheText:
    """R1.41 — the fake's claims about Chromium's requests, made good."""

    def test_an_image_is_not_asked_for(self):
        """Example 1: the one where the diagram draws no text."""
        site = drawn_site(escalation=shell("/api/escalation"))
        elsewhere = Elsewhere()

        item = drawer(site, elsewhere).fetch("escalation")

        assert DIAGRAM not in site.urls_asked() and elsewhere.sent == []
        assert "![Escalation diagram](escalation-diagram.png)" in note(item.payload)

    def test_a_request_robots_txt_disallows_is_not_asked_for(self):
        """Example 2: the one where `/api/` is kept out."""
        site = drawn_site(escalation=shell("/api/escalation"))
        site.responses[ROBOTS] = httpx.Response(200, text="User-agent: *\nDisallow: /api/\n")

        item = drawer(site, Elsewhere()).fetch("escalation")

        assert API not in site.urls_asked()
        assert TEXT not in note(item.payload)

    def test_a_429_while_drawing_fails_the_page(self):
        """Example 3: the one where `/api/escalation` says slow down (R1.35)."""
        site = drawn_site(escalation=shell("/api/escalation"))
        site.responses[API] = httpx.Response(429)

        with pytest.raises(WebRequestFailed) as raised:
            drawer(site, Elsewhere()).fetch("escalation")

        assert API in str(raised.value) and "429" in str(raised.value)

    def test_a_script_is_asked_once_however_many_pages_load_it(self):
        """Example 5: the one where one crawl draws `index` and `escalation`."""
        site = drawn_site(index=shell("/api/index"), escalation=shell("/api/escalation"))
        site.responses[ROBOTS] = httpx.Response(
            200, text="User-agent: *\nDisallow: /ops/drafts/\n"
        )

        keys = [ref.key for ref in drawer(site, Elsewhere(), crawl=50).list(None)]

        assert "escalation" in keys and "index" in keys
        assert Counter(site.urls_asked())[APP] == 1

    def test_a_script_moving_the_browser_away_is_not_followed(self):
        """Example 6: the one where a navigation answered `204` leaves the page drawn."""
        site = drawn_site(
            escalation=shell("/api/escalation", attributes=' data-go="/ops/login"')
        )

        item = drawer(site, Elsewhere()).fetch("escalation")

        assert f"{SITE}/ops/login" not in site.urls_asked()
        assert b"<h1>Escalation</h1>" in item.payload

    def test_another_frames_page_is_not_asked_for(self):
        """Example 7: the one where the page embeds a video."""
        frame = "https://video.example.org/embed"
        site = drawn_site(
            escalation=shell("/api/escalation", extra=f'<iframe src="{frame}"></iframe>')
        )
        elsewhere = Elsewhere()

        drawer(site, elsewhere).fetch("escalation")

        assert frame not in [asked.url for asked in elsewhere.sent]

    def test_nothing_but_get_is_sent(self):
        """Example 8: the one where a script counts a view (R1.1)."""
        views = f"{SITE}/api/views"
        site = drawn_site(
            escalation=shell("/api/escalation", attributes=' data-post="/api/views"')
        )
        elsewhere = Elsewhere()

        drawer(site, elsewhere).fetch("escalation")

        assert views not in site.urls_asked() and elsewhere.sent == []

    def test_a_request_to_another_host_is_the_browsers_to_send(self):
        """Counter-example, row 9: the one where the script comes from a CDN."""
        site = drawn_site(escalation=shell("/api/escalation", app=CDN))
        elsewhere = Elsewhere()

        item = drawer(site, elsewhere).fetch("escalation")

        assert [asked.url for asked in elsewhere.sent] == [CDN]
        assert b"<h1>Escalation</h1>" in item.payload
