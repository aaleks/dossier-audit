"""R1.35 — once its site answers `429`, a web source asks it nothing more that sync.

`djangoproject.com` refused 70 of the 91 pages under `/foundation/` within seven
seconds, and was asked for all 70 after its first refusal. A site that says it is
asked too often is not asked again seconds later; what could not be fetched is
owed to the next sync (R2.23), and `delay:` is how to ask it more slowly (R1.36).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from tests.docs_site import ROBOTS, SITE, SITEMAP, URL, DocsSite

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.infrastructure.connectors.web import WebConnector, WebRequestFailed
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

ESCALATION = f"{SITE}/ops/escalation"
INDEX = f"{SITE}/ops/"
MATRIX = f"{SITE}/ops/escalation-matrix.pdf"
SOURCE = SourceConfig(id="vendor-docs", type="web", options={"url": URL})
NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)

TOO_MANY = httpx.Response(429)


class TestAWebSourceStopsAskingASiteThatAnswered429:
    """R1.35 — one refusal ends the sync's requests to the site."""

    def test_a_page_after_the_refusal_is_not_asked_for(self):
        """Example 1: the one where `index` comes after `escalation` was refused."""
        site = DocsSite(responses={ESCALATION: TOO_MANY})
        connector = WebConnector(url=URL, transport=site.transport())
        with pytest.raises(WebRequestFailed):
            connector.fetch("escalation")

        with pytest.raises(WebRequestFailed) as raised:
            connector.fetch("index")

        message = str(raised.value)
        assert ESCALATION in message and "429" in message and "delay:" in message
        assert INDEX not in site.urls_asked()

    def test_a_sync_owes_every_page_from_the_refused_one_on(self, tmp_path: Path):
        """Example 2: the one where the PDF is refused and nothing after it is asked."""
        site = DocsSite(responses={MATRIX: TOO_MANY})
        ledger = Ledger(tmp_path)
        try:
            report = sync_source(
                config=SOURCE,
                connector=WebConnector(url=URL, transport=site.transport()),
                store=SnapshotStore(tmp_path),
                ledger=ledger,
                now=NOW,
            )

            refused = ["escalation-matrix.pdf", "index", "runbooks/dns-failover.html"]
            assert report.new == 1
            assert sorted(report.failed) == refused
            assert sorted(key for key, _ in ledger.owed("vendor-docs")) == refused
            assert site.urls_asked()[-1] == MATRIX
        finally:
            ledger.close()

    def test_robots_txt_answered_429_fails_the_listing(self):
        """Example 3: the one where the site refuses before its sitemap is read."""
        site = DocsSite(responses={ROBOTS: TOO_MANY})
        connector = WebConnector(url=URL, transport=site.transport())

        with pytest.raises(WebRequestFailed) as raised:
            list(connector.list(None))

        assert ROBOTS in str(raised.value) and "429" in str(raised.value)
        assert SITEMAP not in site.urls_asked()

    def test_the_next_syncs_connector_asks_again(self):
        """Counter-example, row 4: the one where a refusal lasts one sync."""
        site = DocsSite(responses={ESCALATION: TOO_MANY})
        with pytest.raises(WebRequestFailed):
            WebConnector(url=URL, transport=site.transport()).fetch("escalation")
        site.responses.clear()

        item = WebConnector(url=URL, transport=site.transport()).fetch("escalation")

        assert item.key == "escalation"

    def test_a_missing_page_does_not_stop_the_sync(self):
        """Counter-example, row 5: the one where `escalation` is `404`."""
        site = DocsSite(responses={ESCALATION: httpx.Response(404)})
        connector = WebConnector(url=URL, transport=site.transport())
        with pytest.raises(WebRequestFailed):
            connector.fetch("escalation")

        item = connector.fetch("index")

        assert item.key == "index"
        assert INDEX in site.urls_asked()
