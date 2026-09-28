"""R1.40 — with `render: browser`, a web page answered as HTML is held as a
headless browser draws it.

A site that sends a page as a script that writes it sends a shell: held as
sent, the page has nothing in it to read. With `render: browser` the page is
asked as every page is, and what the site sent is handed to a browser, which
runs its scripts; the page is held as the browser then holds it, in the charset
it was read in. A crawl reads its links from the drawn page.

`tests.drawing.FakeBrowser` draws here. The same shells are drawn by a real
headless Chromium in `tests/integration/test_R001_40__…`.
"""

from __future__ import annotations

import codecs
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.docs_site import ROBOTS, SITE, URL, DocsSite
from tests.drawing import API, APP, TEXT, FakeBrowser, drawn_site, html, shell

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.infrastructure.connectors.browser import DrawFailed
from dossier.infrastructure.connectors.web import WebConnector, WebRequestFailed
from dossier.infrastructure.converters.html_markdown import HtmlMarkdownConverter
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

ESCALATION = f"{SITE}/ops/escalation"
MATRIX = f"{SITE}/ops/escalation-matrix.pdf"


def connector(site: DocsSite, browser, **options) -> WebConnector:
    return WebConnector(
        url=URL, render="browser", browser=browser, transport=site.transport(), **options
    )


def note(payload: bytes) -> str:
    return HtmlMarkdownConverter().convert(payload, {}).decode("utf-8")


class TestAPageIsHeldAsABrowserDrawsIt:
    """R1.40 — the page its scripts draw, not the shell its server sends."""

    def test_the_drawn_page_is_held_and_its_note_is_its_text(self):
        """Example 1: the one where `escalation` is a shell its script fills."""
        site = drawn_site(escalation=shell("/api/escalation"))

        item = connector(site, FakeBrowser()).fetch("escalation")

        assert b"<h1>Escalation</h1>" in item.payload
        written = note(item.payload)
        assert written.startswith("# Escalation\n") and TEXT in written

    def test_the_page_is_asked_once_and_by_dossier(self, tmp_path: Path):
        """Example 2: the one where the browser is handed the page, and asks for the rest."""
        site = drawn_site(escalation=shell("/api/escalation"))
        with Ledger(tmp_path) as ledger:
            sync_source(
                config=SourceConfig(
                    id="vendor-docs", type="web", options={"url": URL, "render": "browser"}
                ),
                connector=connector(site, FakeBrowser()),
                store=SnapshotStore(tmp_path),
                ledger=ledger,
                now=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
            )

        asked = Counter(site.urls_asked())
        assert asked[ESCALATION] == 1
        assert asked[APP] == 1 and asked[API] == 1

    def test_a_crawl_follows_the_links_a_script_draws(self):
        """Example 3: the one where `index`'s menu is written by its script."""
        site = drawn_site(index=shell("/api/index"))
        site.responses[ROBOTS] = html("User-agent: *\nDisallow: /ops/drafts/\n")
        crawler = connector(site, FakeBrowser(), crawl=50)

        keys = [ref.key for ref in crawler.list(None)]

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

        item = connector(site, FakeBrowser()).fetch("escalation")

        assert item.payload.startswith(codecs.BOM_UTF8)
        text = item.payload.decode("utf-8-sig")
        assert "Déclaré" in text and "résolu" in text
        written = note(item.payload)
        assert "Déclaré" in written and "résolu" in written

    def test_without_render_the_shell_is_held(self):
        """Counter-example, row 5: the one where nothing draws the page."""
        site = drawn_site(escalation=shell("/api/escalation"))
        browser = FakeBrowser()

        item = WebConnector(url=URL, browser=browser, transport=site.transport()).fetch(
            "escalation"
        )

        assert b"<h1>Escalation</h1>" not in item.payload
        assert "# Escalation" not in note(item.payload) and TEXT not in note(item.payload)
        assert browser.opened == 0

    def test_a_page_that_is_not_html_is_held_as_sent(self):
        """Counter-example, row 6: the one where the PDF is not drawn."""
        site = drawn_site()
        browser = FakeBrowser()

        item = connector(site, browser).fetch("escalation-matrix.pdf")

        assert item.media_type == "application/pdf" and item.payload == b"%PDF-1.7\n"
        assert browser.opened == 0

    def test_a_page_that_never_goes_quiet_fails(self):
        """Counter-example, row 7: the one where half a page would be held."""

        class NeverQuiet(FakeBrowser):
            def draw(self, url, decide):
                raise DrawFailed(
                    f"{url} did not finish drawing: its requests had not gone quiet"
                )

        site = drawn_site(escalation=shell("/api/escalation"))

        with pytest.raises(WebRequestFailed) as raised:
            connector(site, NeverQuiet()).fetch("escalation")

        assert ESCALATION in str(raised.value) and "quiet" in str(raised.value)

    def test_render_added_to_a_held_source_draws_every_page_once(self, tmp_path: Path):
        """Example 8: the one where no `<lastmod>` moved, and the shells are drawn anyway."""
        site = drawn_site(escalation=shell("/api/escalation"))
        plain = SourceConfig(id="vendor-docs", type="web", options={"url": URL})
        drawn = SourceConfig(
            id="vendor-docs", type="web", options={"url": URL, "render": "browser"}
        )
        synced(tmp_path, plain, WebConnector(url=URL, transport=site.transport()), day=6)

        report = synced(tmp_path, drawn, connector(site, FakeBrowser()), day=7)

        # The three HTML pages are held as drawn now; the PDF is held as sent.
        assert report.fetched == 4 and report.changed == 3
        with Ledger(tmp_path) as ledger:
            held = SnapshotStore(tmp_path).get(ledger.row("vendor-docs", "escalation").snapshot)
        assert b"<h1>Escalation</h1>" in held

    def test_the_sync_after_that_fetches_nothing(self, tmp_path: Path):
        """Counter-example, row 9: the one where the hash is recorded."""
        site = drawn_site(escalation=shell("/api/escalation"))
        plain = SourceConfig(id="vendor-docs", type="web", options={"url": URL})
        drawn = SourceConfig(
            id="vendor-docs", type="web", options={"url": URL, "render": "browser"}
        )
        synced(tmp_path, plain, WebConnector(url=URL, transport=site.transport()), day=6)
        synced(tmp_path, drawn, connector(site, FakeBrowser()), day=7)

        report = synced(tmp_path, drawn, connector(site, FakeBrowser()), day=8)

        assert report.fetched == 1  # the one page with no `<lastmod>`, as ever (R1.31)
        assert report.changed == 0


def synced(workspace: Path, config: SourceConfig, web: WebConnector, *, day: int):
    with Ledger(workspace) as ledger:
        return sync_source(
            config=config,
            connector=web,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=datetime(2026, 8, day, 9, 0, tzinfo=UTC),
        )
