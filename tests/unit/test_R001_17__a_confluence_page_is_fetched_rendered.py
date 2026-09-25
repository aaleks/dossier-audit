"""R1.17 — a Confluence page is fetched as Confluence renders it for export, and
labelled a Confluence page.

The rendered body, not the storage format: storage holds macros only Confluence
can draw. The page is stored as Confluence sent it (R1.2), render-time noise
included, and labelled with a type that only a Confluence page carries, so the
converter reading it claims nothing else (R8.19). A file the page carries is
still what Confluence says that file is (R2.16).

The page is `tests/fixtures/confluence/81920114.json`, in the shape Confluence
Data Center 9.2 sends. Every request goes through an `httpx.MockTransport`. No
socket is opened.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from dossier.domain.conversion import CONFLUENCE_PAGE
from dossier.infrastructure.connectors.confluence import ConfluenceConnector

BASE = "https://confluence.example.internal"
PAGE = "81920114"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "confluence"
SENT = (FIXTURE / f"{PAGE}.json").read_bytes()
FILES = (FIXTURE / f"{PAGE}-attachments.json").read_bytes()


class Confluence:
    """Data Center answering `OPS-114` and its files, remembering what it was asked."""

    def __init__(self) -> None:
        self.asked: list[httpx.URL] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.asked.append(request.url)
            path = request.url.path
            if path == f"/rest/api/content/{PAGE}":
                return httpx.Response(
                    200, content=SENT, headers={"content-type": "application/json"}
                )
            if path == f"/rest/api/content/{PAGE}/child/attachment":
                return httpx.Response(200, content=FILES)
            if path.startswith(f"/download/attachments/{PAGE}/"):
                return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n")
            return httpx.Response(404)

        return httpx.MockTransport(handle)


def connector(server: Confluence) -> ConfluenceConnector:
    return ConfluenceConnector(base_url=BASE, query="space = OPS", transport=server.transport())


class TestAConfluencePageIsFetchedRendered:
    """R1.17 — the page a reader sees, as Confluence sent it, under its own type."""

    def test_a_page_is_fetched_with_its_export_view_and_labelled_a_confluence_page(self):
        """Example 1: the one where `81920114` is asked for rendered for export."""
        server = Confluence()

        fetched = connector(server).fetch(PAGE)

        (asked,) = server.asked
        assert asked.path == f"/rest/api/content/{PAGE}"
        assert asked.params["expand"] == "body.export_view,version,space"
        assert fetched.payload == SENT
        assert fetched.media_type == CONFLUENCE_PAGE
        assert CONFLUENCE_PAGE == "application/vnd.dossier.confluence-page+json"
        assert fetched.remote_version == "v37"

    def test_the_render_time_table_of_contents_is_stored_as_sent(self):
        """Counter-example, row 2: the one where the payload changes between renders.

        The class name holds the time the macro was drawn. It is kept: what a
        stage reads is the converter's decision (R8.20), and bytes edited here
        would be hashed from something nobody received.
        """
        fetched = connector(Confluence()).fetch(PAGE)

        assert b"rbtoc1786032120000" in fetched.payload
        body = json.loads(fetched.payload)["body"]["export_view"]["value"]
        assert "toc-macro" in body

    def test_a_file_the_page_carries_is_labelled_as_confluence_reports_it(self):
        """Counter-example, row 3: the one where the page's type is not the file's."""
        fetched = connector(Confluence()).fetch(f"{PAGE}/escalation-matrix.png")

        assert fetched.media_type == "image/png"
