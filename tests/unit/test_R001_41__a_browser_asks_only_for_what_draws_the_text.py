"""R1.41 — a browser drawing a page asks for no image, font, media or other page,
sends nothing but `GET`, and asks its site only as the site's pages are asked.

Every request a page being drawn makes comes back to the connector. The page's
own document is answered with what the site already sent; a request to the site
goes through the path every request to it takes, so `robots.txt`, `delay:` and a
`429` hold (R1.33, R1.35, R1.36), and a script or stylesheet is asked once a
sync; a request to another host is the page's own, and the browser sends it.
Nothing else is asked: no image, video, audio or font, no other page, and
nothing but `GET`, which is all a connector ever sends (R1.1).

`tests.drawing.FakeBrowser` makes the requests here, in the order Chromium
makes them. `tests/integration/test_R001_41__…` has a real Chromium make them.
"""

from __future__ import annotations

from collections import Counter

import httpx
import pytest
from tests.docs_site import ROBOTS, SITE, URL, DocsSite
from tests.drawing import API, APP, DIAGRAM, TEXT, FakeBrowser, drawn_site, shell

from dossier.domain.web import browser_asks
from dossier.infrastructure.connectors.web import WebConnector, WebRequestFailed
from dossier.infrastructure.converters.html_markdown import HtmlMarkdownConverter

ESCALATION = f"{SITE}/ops/escalation"
PAGE = f"{SITE}/ops/escalation"


class Clock:
    """Seconds that pass only when the connector waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


def drawer(site: DocsSite, browser: FakeBrowser, **options) -> WebConnector:
    return WebConnector(
        url=URL, render="browser", browser=browser, transport=site.transport(), **options
    )


def note(payload: bytes) -> str:
    return HtmlMarkdownConverter().convert(payload, {}).decode("utf-8")


class TestABrowserAsksOnlyForWhatDrawsTheText:
    """R1.41 — what a page being drawn may ask for, and who asks it."""

    def test_an_image_is_not_asked_for_and_its_alt_text_is_in_the_note(self):
        """Example 1: the one where the diagram draws no text."""
        site = drawn_site(escalation=shell("/api/escalation"))
        browser = FakeBrowser()

        item = drawer(site, browser).fetch("escalation")

        assert DIAGRAM not in site.urls_asked()
        assert DIAGRAM in [asked.url for asked in browser.refused]
        assert "![Escalation diagram](escalation-diagram.png)" in note(item.payload)

    def test_a_request_robots_txt_disallows_is_not_asked_for(self):
        """Example 2: the one where `/api/` is kept out, and the page drawn without it."""
        site = drawn_site(escalation=shell("/api/escalation"))
        site.responses[ROBOTS] = httpx.Response(200, text="User-agent: *\nDisallow: /api/\n")

        item = drawer(site, FakeBrowser()).fetch("escalation")

        assert API not in site.urls_asked()
        assert TEXT not in note(item.payload)

    def test_a_429_while_drawing_fails_the_page_and_asks_nothing_more(self):
        """Example 3: the one where `/api/escalation` says slow down (R1.35)."""
        site = drawn_site(escalation=shell("/api/escalation"))
        site.responses[API] = httpx.Response(429)
        connector = drawer(site, FakeBrowser())

        with pytest.raises(WebRequestFailed) as raised:
            connector.fetch("escalation")
        with pytest.raises(WebRequestFailed):
            connector.fetch("index")

        assert API in str(raised.value) and "429" in str(raised.value)
        assert f"{SITE}/ops/" not in site.urls_asked()

    def test_the_sites_own_requests_keep_its_pace(self):
        """Example 4: the one where `delay: 2` spaces the script and its answer too (R1.36)."""
        site = drawn_site(escalation=shell("/api/escalation"))
        clock = Clock()

        drawer(site, FakeBrowser(), delay=2, sleep=clock.sleep, clock=clock).fetch("escalation")

        # robots.txt, the sitemap, the page, `app.js`, `/api/escalation`.
        assert site.urls_asked()[-3:] == [ESCALATION, APP, API]
        assert clock.waits == [2.0, 2.0, 2.0, 2.0]

    def test_a_script_is_asked_once_however_many_pages_load_it(self):
        """Example 5: the one where `index` and `escalation` both load `app.js`."""
        site = drawn_site(index=shell("/api/index"), escalation=shell("/api/escalation"))
        site.responses[ROBOTS] = httpx.Response(
            200, text="User-agent: *\nDisallow: /ops/drafts/\n"
        )

        keys = [ref.key for ref in drawer(site, FakeBrowser(), crawl=50).list(None)]

        assert "escalation" in keys and "index" in keys
        assert Counter(site.urls_asked())[APP] == 1

    def test_a_script_moving_the_browser_away_is_not_followed(self):
        """Example 6: the one where the page sends the browser to a login form."""
        site = drawn_site(
            escalation=shell("/api/escalation", attributes=' data-go="/ops/login"')
        )

        item = drawer(site, FakeBrowser()).fetch("escalation")

        assert f"{SITE}/ops/login" not in site.urls_asked()
        assert b"<h1>Escalation</h1>" in item.payload

    def test_another_frames_page_is_not_asked_for(self):
        """Example 7: the one where the page embeds a video."""
        frame = "https://video.example.org/embed"
        site = drawn_site(
            escalation=shell("/api/escalation", extra=f'<iframe src="{frame}"></iframe>')
        )
        browser = FakeBrowser()

        drawer(site, browser).fetch("escalation")

        assert frame in [asked.url for asked in browser.refused]
        assert frame not in [asked.url for asked in browser.sent]

    def test_nothing_but_get_is_sent(self):
        """Example 8: the one where a script counts a view (R1.1)."""
        views = f"{SITE}/api/views"
        site = drawn_site(
            escalation=shell("/api/escalation", attributes=' data-post="/api/views"')
        )
        browser = FakeBrowser()

        drawer(site, browser).fetch("escalation")

        assert views not in site.urls_asked()
        assert [asked.method for asked in browser.refused if asked.url == views] == ["POST"]

    def test_a_request_to_another_host_is_the_browsers_to_send(self):
        """Counter-example, row 9: the one where the script comes from a CDN."""
        cdn = "https://cdn.example.net/app.js"
        site = drawn_site(escalation=shell("/api/escalation", app=cdn))
        browser = FakeBrowser()

        drawer(site, browser).fetch("escalation")

        assert [asked.url for asked in browser.sent] == [cdn]
        assert cdn not in site.urls_asked()


class TestWhatBecomesOfEachRequest:
    """R1.41 — the decision, apart from any browser."""

    @pytest.mark.parametrize(
        ("url", "method", "kind", "navigation", "main_frame", "drawn", "expected"),
        [
            (PAGE, "GET", "document", True, True, False, "page"),
            (PAGE, "GET", "document", True, True, True, "stay"),
            (f"{SITE}/ops/login", "GET", "document", True, True, True, "stay"),
            ("https://video.example.org/embed", "GET", "document", True, False, True, "refuse"),
            (f"{SITE}/api/views", "POST", "fetch", False, True, True, "refuse"),
            (DIAGRAM, "GET", "image", False, True, True, "refuse"),
            (f"{SITE}/fonts/inter.woff2", "GET", "font", False, True, True, "refuse"),
            (f"{SITE}/media/walkthrough.mp4", "GET", "media", False, True, True, "refuse"),
            (f"{SITE}/drafts/app.js", "GET", "script", False, True, True, "refuse"),
            (APP, "GET", "script", False, True, True, "site"),
            (API, "GET", "fetch", False, True, True, "site"),
            ("https://cdn.example.net/app.js", "GET", "script", False, True, True, "send"),
        ],
    )
    def test_each_request_is_answered_sent_or_refused(
        self, url, method, kind, navigation, main_frame, drawn, expected
    ):
        verdict = browser_asks(
            url=url,
            method=method,
            kind=kind,
            navigation=navigation,
            main_frame=main_frame,
            page=PAGE,
            drawn=drawn,
            allowed=lambda target: "/drafts/" not in target,
        )

        assert verdict == expected
