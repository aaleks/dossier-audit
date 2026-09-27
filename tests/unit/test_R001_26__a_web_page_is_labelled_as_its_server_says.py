"""R1.26 — a web page is labelled with the media type its `Content-Type` header states.

What the server said wins over what the URL's name suggests (R2.16), and the
bytes are kept as sent (R1.2).
"""

from __future__ import annotations

import httpx
from tests.docs_site import HTML, SITE, URL, DocsSite

from dossier.infrastructure.connectors.web import WebConnector

BODY = b"<html><body><h1>Escalation</h1>\r\n<p>Ruf an</p></body></html>"


def fetched(key: str, site: DocsSite):
    return WebConnector(url=URL, transport=site.transport()).fetch(key)


class TestAWebPageIsLabelledAsItsServerSays:
    """R1.26 — `Content-Type`, canonical, and nothing else."""

    def test_an_html_page_is_text_html_and_its_bytes_as_sent(self):
        """Example 1: the one where `escalation` is served `text/html; charset=utf-8`."""
        site = DocsSite(
            responses={
                f"{SITE}/ops/escalation": httpx.Response(
                    200, headers={"Content-Type": HTML}, content=BODY
                )
            }
        )

        item = fetched("escalation", site)

        assert item.media_type == "text/html"
        assert item.payload == BODY
        assert item.key == "escalation"

    def test_a_pdf_the_sitemap_lists_is_a_pdf(self):
        """Example 2: the one where `escalation-matrix.pdf` is served as a PDF."""
        item = fetched("escalation-matrix.pdf", DocsSite())

        assert item.media_type == "application/pdf"
        assert item.payload.startswith(b"%PDF-")

    def test_a_web_page_carries_no_files(self):
        """Example 3: the one where `attachments("escalation")` is empty, and asks nothing."""
        site = DocsSite()
        connector = WebConnector(url=URL, transport=site.transport())

        assert list(connector.attachments("escalation")) == []
        assert site.asked == []

    def test_a_name_ending_html_served_as_text_is_text(self):
        """Counter-example, row 4: the one where `dns-failover.html` is served `text/plain`."""
        site = DocsSite(
            responses={
                f"{SITE}/ops/runbooks/dns-failover.html": httpx.Response(
                    200, headers={"Content-Type": "text/plain"}, content=b"dig +trace"
                )
            }
        )

        assert fetched("runbooks/dns-failover.html", site).media_type == "text/plain"

    def test_a_response_with_no_content_type_is_octet_stream(self):
        """Counter-example, row 5: the one where the server says nothing about the bytes."""
        site = DocsSite(responses={f"{SITE}/ops/escalation": httpx.Response(200, content=BODY)})

        assert fetched("escalation", site).media_type == "application/octet-stream"
