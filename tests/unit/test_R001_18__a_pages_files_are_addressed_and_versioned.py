"""R1.18 — a page's files are addressed `<page id>/<filename>`, and a file's marker
is its attachment id and version.

Confluence keeps an attachment's id when a file is uploaded again under the same
name, and raises its version. A file deleted and uploaded again gets a new id
and starts at version 1 again. The id alone misses the first case and the
version alone the second.

Row 1 and row 3 read `tests/fixtures/confluence/81920114-attachments.json`, the
listing in the shape Confluence Data Center 9.2 sends. Every request goes
through an `httpx.MockTransport`. No socket is opened.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from dossier.domain.sync import needs_fetch
from dossier.infrastructure.connectors.confluence import ConfluenceConnector

BASE = "https://confluence.example.internal"
PAGE = "81920114"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "confluence"
LISTING = json.loads((FIXTURE / f"{PAGE}-attachments.json").read_bytes())
PNG = b"\x89PNG\r\n\x1a\n not really the rest of a PNG"


def attachment(name: str, id_: str, number: int) -> dict:
    return {
        "id": id_,
        "type": "attachment",
        "title": name,
        "version": {"number": number},
        "extensions": {"mediaType": "image/png"},
        "_links": {"download": f"/download/attachments/{PAGE}/{name}?version={number}&api=v2"},
    }


class Confluence:
    """A page carrying `files`, listed `per` at a time, each downloadable."""

    def __init__(self, files: list[dict], per: int = 50) -> None:
        self.files = files
        self.per = per
        self.asked: list[str] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.asked.append(str(request.url))
            path = request.url.path
            if path == f"/rest/api/content/{PAGE}/child/attachment":
                query = parse_qs(request.url.query.decode())
                start = int(query.get("start", ["0"])[0])
                limit = min(int(query.get("limit", ["50"])[0]), self.per)
                results = self.files[start : start + limit]
                links: dict[str, str] = {"base": BASE, "context": ""}
                if start + limit < len(self.files):
                    links["next"] = f"{path}?start={start + limit}&limit={limit}"
                return httpx.Response(
                    200,
                    json={
                        "results": results,
                        "start": start,
                        "limit": limit,
                        "size": len(results),
                        "_links": links,
                    },
                )
            if path.startswith(f"/download/attachments/{PAGE}/"):
                return httpx.Response(
                    200, content=PNG, headers={"content-type": "application/octet-stream"}
                )
            return httpx.Response(404)

        return httpx.MockTransport(handle)


def connector(server: Confluence) -> ConfluenceConnector:
    return ConfluenceConnector(base_url=BASE, query="space = OPS", transport=server.transport())


class TestAPagesFilesAreAddressedAndVersioned:
    """R1.18 — each file has its own address, and a marker that moves when its bytes can."""

    def test_a_file_is_addressed_under_its_page_with_its_id_and_version(self):
        """Example 1: the one where `escalation-matrix.png` is id 81920301 at version 2."""
        server = Confluence(LISTING["results"])

        (ref,) = connector(server).attachments(PAGE)

        assert ref.key == f"{PAGE}/escalation-matrix.png"
        assert ref.item_key == PAGE
        assert ref.remote_version == "81920301:v2"

    def test_a_file_uploaded_again_moves_its_marker_and_not_its_pages(self):
        """Example 2: the one where the file is at version 3 and the page untouched."""
        server = Confluence([attachment("escalation-matrix.png", "81920301", 3)])

        (ref,) = connector(server).attachments(PAGE)

        assert ref.remote_version == "81920301:v3"
        assert needs_fetch(recorded_version="81920301:v2", listed_version=ref.remote_version)
        assert not needs_fetch(recorded_version="v37", listed_version="v37")

    def test_a_file_is_fetched_from_its_download_link_as_confluence_labels_it(self):
        """Example 3: the one where the bytes come from `_links.download`."""
        server = Confluence(LISTING["results"])

        fetched = connector(server).fetch(f"{PAGE}/escalation-matrix.png")

        assert fetched.key == f"{PAGE}/escalation-matrix.png"
        assert fetched.payload == PNG
        # What Confluence records about the file, over the transport's header (R2.16).
        assert fetched.media_type == "image/png"
        assert fetched.remote_version == "81920301:v2"
        assert server.asked[-1] == (
            f"{BASE}/download/attachments/{PAGE}/escalation-matrix.png"
            "?version=2&modificationDate=1785842400000&api=v2"
        )

    def test_every_file_is_listed_across_pages_of_the_listing(self):
        """Example 4: the one where 30 files come back 25 at a time."""
        files = [attachment(f"shot-{n:02}.png", str(81920400 + n), 1) for n in range(30)]
        server = Confluence(files, per=25)

        refs = list(connector(server).attachments(PAGE))

        assert [ref.key for ref in refs] == [f"{PAGE}/shot-{n:02}.png" for n in range(30)]
        assert sum("/child/attachment" in url for url in server.asked) == 2

    def test_a_file_deleted_and_uploaded_again_has_a_new_marker(self):
        """Counter-example, row 5: the one where the version reads `v1` both times."""
        before = Confluence([attachment("escalation-matrix.png", "81920301", 1)])
        after = Confluence([attachment("escalation-matrix.png", "81920377", 1)])

        (old,) = connector(before).attachments(PAGE)
        (new,) = connector(after).attachments(PAGE)

        assert (old.remote_version, new.remote_version) == ("81920301:v1", "81920377:v1")
        assert needs_fetch(
            recorded_version=old.remote_version, listed_version=new.remote_version
        )
