"""R1.20 — an export that is refused, or answered with anything but a PDF, fails
that document and says why.

`export: pdf` is the workspace's statement that the server exports. When it
does not, the fix is a key in `sources.yaml` or a permission on the server, and
neither can be made from inside the connector -- as R1.12 found for a refused
credential. So the export is not asked again another way, and not dropped from
the listing: a PDF missing without a word reads exactly like a page that has
none.

`cwiki.apache.org` and `confluence.ecmwf.int` both answer the export `403` to an
anonymous reader while serving the page's JSON. Every request goes through an
`httpx.MockTransport`. No socket is opened.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.sync import State
from dossier.infrastructure.connectors.confluence import ConfluenceConnector
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

BASE = "https://confluence.example.internal"
PAGE = "81920114"
EXPORT = "/spaces/flyingpdf/pdfpageexport.action"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "confluence"
SENT = (FIXTURE / f"{PAGE}.json").read_bytes()
SOURCE = SourceConfig(id="procedures-confluence", type="confluence", options={})
NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
LOGIN = "<html><head><title>Log In - Confluence</title></head><body>Log in</body></html>"


class Confluence:
    """Data Center serving `OPS-114` and its file, and answering the export with `export`."""

    def __init__(self, export: httpx.Response) -> None:
        self.export = export
        self.asked: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.asked.append(request)
            path = request.url.path
            if path == "/rest/api/content/search":
                page = {"id": PAGE, "type": "page", "version": {"number": 37}}
                return httpx.Response(200, json={"results": [page], "_links": {}})
            if path == f"/rest/api/content/{PAGE}":
                return httpx.Response(200, content=SENT)
            if path == f"/rest/api/content/{PAGE}/child/attachment":
                matrix = {
                    "id": "81920301",
                    "title": "escalation-matrix.png",
                    "version": {"number": 2},
                    "extensions": {"mediaType": "image/png"},
                    "_links": {
                        "download": f"/download/attachments/{PAGE}/escalation-matrix.png"
                    },
                }
                return httpx.Response(200, json={"results": [matrix], "_links": {}})
            if path.startswith(f"/download/attachments/{PAGE}/"):
                return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n")
            if path == EXPORT:
                return self.export
            return httpx.Response(404)

        return httpx.MockTransport(handle)

    def exports_asked(self) -> list[httpx.Request]:
        return [request for request in self.asked if request.url.path == EXPORT]


def sync(workspace: Path, server: Confluence, *, now: datetime = NOW):
    connector = ConfluenceConnector(
        base_url=BASE, query="space = OPS", export="pdf", transport=server.transport()
    )
    with Ledger(workspace) as ledger:
        return sync_source(
            config=SOURCE,
            connector=connector,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
        )


class TestARefusedExportFailsItsDocument:
    """R1.20 — said, not skipped, and not worked around."""

    def test_a_refused_export_fails_its_document_and_nothing_else(self, tmp_path: Path):
        """Example 1: the one where the server answers the export `403`."""
        report = sync(tmp_path, Confluence(httpx.Response(403, text="Forbidden")))

        ((key, message),) = report.failures
        assert key == f"{PAGE}.pdf"
        assert f"{BASE}{EXPORT}?pageId={PAGE}" in message
        assert "403" in message
        assert "`export: pdf`" in message and "refuses" in message
        with Ledger(tmp_path) as ledger:
            assert ledger.row(SOURCE.id, PAGE).state is State.ACTIVE
            assert ledger.row(SOURCE.id, f"{PAGE}/escalation-matrix.png").state is State.ACTIVE
            assert ledger.row(SOURCE.id, f"{PAGE}.pdf") is None
            # R2.8: a partial sync is not mistaken for a complete one.
            assert ledger.watermark(SOURCE.id) is None

    def test_a_login_page_is_never_stored_as_a_pdf(self, tmp_path: Path):
        """Counter-example, row 2: the one where the export answers `200` with HTML."""
        login = httpx.Response(
            200, text=LOGIN, headers={"content-type": "text/html;charset=UTF-8"}
        )

        report = sync(tmp_path, Confluence(login))

        ((key, message),) = report.failures
        assert key == f"{PAGE}.pdf"
        assert "text/html" in message
        with Ledger(tmp_path) as ledger:
            assert ledger.row(SOURCE.id, f"{PAGE}.pdf") is None

    def test_the_next_sync_asks_again_once_and_the_same_way(self, tmp_path: Path):
        """Counter-example, row 3: the one where nothing is retried and nothing is dropped."""
        server = Confluence(httpx.Response(403, text="Forbidden"))

        sync(tmp_path, server)
        again = sync(tmp_path, server, now=LATER)

        assert [key for key, _ in again.failures] == [f"{PAGE}.pdf"]
        asked = server.exports_asked()
        assert len(asked) == 2  # once per sync
        assert all(request.headers.get("x-atlassian-token") == "no-check" for request in asked)
