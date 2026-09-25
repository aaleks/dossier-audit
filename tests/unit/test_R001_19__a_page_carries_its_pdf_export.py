"""R1.19 — with `export: pdf`, a page also carries its PDF export, keyed `<page id>.pdf`.

The export is a user-interface action, not a REST route. Confluence refuses it
without `X-Atlassian-Token: no-check`, answers it with a `302` to a file under
`/download/export/`, and serves that file only to the session that asked, by
cookie. The fake below does all three, as `confluence.atlassian.com` (Data
Center) did when checked.

The export's marker is the page's, followed by `+` and the first twelve hex digits
of the SHA-256 of the page's file markers, sorted and joined by newlines. An
image replaced in place leaves the page at its version and changes the PDF,
which draws it. The composition is decided in the domain.

Every request goes through an `httpx.MockTransport`. No socket is opened.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from dossier.application.sync import sync_source
from dossier.config.load import ConfigError, load_sources
from dossier.domain.confluence import export_version
from dossier.domain.pipeline import SourceConfig
from dossier.domain.sync import State
from dossier.infrastructure.connectors.confluence import ConfluenceConnector, ConfluenceKeys
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

BASE = "https://confluence.example.internal"
PAGE = "81920114"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "confluence"
SENT = (FIXTURE / f"{PAGE}.json").read_bytes()
EXPORT = "/spaces/flyingpdf/pdfpageexport.action"
FILE = "/download/export/pdfexport-20260805-160200-1/OPS-114.pdf"
PDF = b"%PDF-1.5\n not the rest of a PDF\n%%EOF\n"
NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


def file(name: str, id_: str, number: int) -> dict:
    return {
        "id": id_,
        "type": "attachment",
        "title": name,
        "version": {"number": number},
        "extensions": {"mediaType": "image/png"},
        "_links": {"download": f"/download/attachments/{PAGE}/{name}?version={number}"},
    }


MATRIX = file("escalation-matrix.png", "81920301", 2)


class Confluence:
    """Data Center holding `OPS-114` at version 37, and exporting it as Confluence does."""

    def __init__(self, files: list[dict] | None = None) -> None:
        self.files = [MATRIX] if files is None else files
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
                return httpx.Response(200, json={"results": self.files, "_links": {}})
            if path.startswith(f"/download/attachments/{PAGE}/"):
                return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n")
            if path == EXPORT:
                if request.headers.get("x-atlassian-token") != "no-check":
                    return httpx.Response(403, text="XSRF check failed")
                return httpx.Response(
                    302,
                    headers={
                        "location": f"{FILE}?contentType=application/pdf",
                        "set-cookie": "JSESSIONID=export-session; Path=/",
                    },
                )
            if path == FILE:
                if "JSESSIONID=export-session" not in request.headers.get("cookie", ""):
                    return httpx.Response(403, text="Forbidden")
                return httpx.Response(
                    200, content=PDF, headers={"content-type": "application/pdf;charset=UTF-8"}
                )
            return httpx.Response(404)

        return httpx.MockTransport(handle)


def connector(server: Confluence, export: str | None = "pdf") -> ConfluenceConnector:
    return ConfluenceConnector(
        base_url=BASE, query="space = OPS", export=export, transport=server.transport()
    )


def digest(*markers: str) -> str:
    return hashlib.sha256("\n".join(sorted(markers)).encode("utf-8")).hexdigest()[:12]


class TestAPageCarriesItsPdfExport:
    """R1.19 — the export is a file the page carries, its marker moving with what it draws."""

    def test_the_export_is_carried_by_the_page_beside_its_files(self):
        """Example 1: the one where `81920114` at `v37` carries `escalation-matrix.png`."""
        refs = list(connector(Confluence()).attachments(PAGE))

        assert [(ref.key, ref.item_key) for ref in refs] == [
            (f"{PAGE}/escalation-matrix.png", PAGE),
            (f"{PAGE}.pdf", PAGE),
        ]
        assert refs[1].remote_version == f"v37+{digest('81920301:v2')}"

    def test_the_export_is_fetched_through_the_action_in_one_session(self):
        """Example 2: the one where the header opens the action and the cookie the file."""
        server = Confluence()

        fetched = connector(server).fetch(f"{PAGE}.pdf")

        asked = server.asked[-2:]
        assert (asked[0].url.path, asked[0].url.params["pageId"]) == (EXPORT, PAGE)
        assert asked[0].headers["x-atlassian-token"] == "no-check"
        assert asked[1].url.path == FILE
        assert fetched.key == f"{PAGE}.pdf"
        assert fetched.payload == PDF
        assert fetched.media_type == "application/pdf"
        assert all(request.method == "GET" for request in server.asked)

    def test_an_image_uploaded_again_moves_the_exports_marker(self):
        """Example 3: the one where the page stays at `v37` and the PDF does not."""
        before = list(connector(Confluence()).attachments(PAGE))[-1]
        after = list(
            connector(Confluence([file("escalation-matrix.png", "81920301", 3)])).attachments(
                PAGE
            )
        )[-1]

        assert before.remote_version != after.remote_version
        assert after.remote_version == f"v37+{digest('81920301:v3')}"

    def test_a_page_carrying_no_files_has_the_pages_marker(self):
        """Counter-example, row 4: the one with nothing to digest."""
        (export,) = connector(Confluence(files=[])).attachments(PAGE)

        assert (export.key, export.remote_version) == (f"{PAGE}.pdf", "v37")

    def test_without_export_no_pdf_is_listed_or_asked_for(self):
        """Counter-example, row 5: the one where `export:` is absent."""
        server = Confluence()

        refs = list(connector(server, export=None).attachments(PAGE))

        assert [ref.key for ref in refs] == [f"{PAGE}/escalation-matrix.png"]
        assert not any(request.url.path == EXPORT for request in server.asked)

    def test_taking_export_away_tombstones_every_pdf(self, tmp_path: Path):
        """Counter-example, row 6: the one where the page no longer carries its export."""
        config = SourceConfig(id="procedures-confluence", type="confluence", options={})

        def sync(export: str | None):
            with Ledger(tmp_path) as ledger:
                return sync_source(
                    config=config,
                    connector=connector(Confluence(), export=export),
                    store=SnapshotStore(tmp_path),
                    ledger=ledger,
                    now=NOW,
                )

        first = sync("pdf")
        second = sync(None)

        assert first.failures == ()
        assert second.departed == (f"{PAGE}.pdf",)
        with Ledger(tmp_path) as ledger:
            assert ledger.row(config.id, f"{PAGE}.pdf").state is State.TOMBSTONED
            assert ledger.row(config.id, PAGE).state is State.ACTIVE

    def test_an_export_the_connector_does_not_make_is_refused_at_load_time(
        self, tmp_path: Path
    ):
        """Counter-example, row 7: the one where `export: docx` is asked for."""
        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n"
            "  - id: procedures-confluence\n"
            "    type: confluence\n"
            f"    url: {BASE}\n"
            "    query: space = OPS\n"
            "    export: docx\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors={"confluence": ConfluenceKeys})

        assert "export" in str(error.value) and "pdf" in str(error.value)


class TestTheExportsMarker:
    """R1.19 — the composition, decided in the domain."""

    def test_the_page_marker_and_a_digest_of_its_files(self):
        assert export_version("v37", ["81920301:v2"]) == f"v37+{digest('81920301:v2')}"

    def test_the_order_files_are_listed_in_does_not_move_it(self):
        one = export_version("v37", ["81920301:v2", "81920302:v1"])
        other = export_version("v37", ["81920302:v1", "81920301:v2"])

        assert one == other

    def test_no_files_is_the_page_marker(self):
        assert export_version("v37", []) == "v37"

    def test_a_marker_nobody_supplied_is_not_made_up(self):
        """The one where the page, or a file, has no marker: nor has the export (R1.5)."""
        assert export_version(None, ["81920301:v2"]) is None
        assert export_version("v37", ["81920301:v2", None]) is None


def test_the_fixture_page_is_at_version_37():
    """The fake's search and the fixture agree, so a version read from either is `v37`."""
    assert json.loads(SENT)["version"]["number"] == 37
