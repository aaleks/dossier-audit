"""R1.22 — a windowed Confluence listing also lists each page the query matches
whose files changed in the window.

CQL's `lastmodified` on a page moves with the page's own version and not with
its files. That was read against Data Center 9.2.21 in Docker: a file uploaded
again left the page at version 1 and out of a windowed `type = page` search, and
only `type = attachment` found it, with the page as its container. So a
windowed listing also asks which files changed in the window, and then which of
their pages the source's query matches (`id in (...)`). The query is never
applied to the files.

Every request goes through an `httpx.MockTransport` playing Data Center. It
answers the three questions the way the live server did, and it names a file's
page only when `expand=container` asks for it, as the live server does. No
socket is opened.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx

from dossier.infrastructure.connectors.confluence import ConfluenceConnector

BASE = "https://confluence.example.internal"
QUERY = "space = OPS"
SINCE = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
# `SINCE` widened by a day, as R1.15 row 2 asks it.
WINDOW = 'lastmodified >= "2026-08-05 09:00"'
PAGE = "81920114"


class Confluence:
    """Pages in spaces, and files on them, some changed inside the window."""

    def __init__(self) -> None:
        # id -> (space, version, edited inside the window)
        self.pages: dict[str, tuple[str, int, bool]] = {}
        # (attachment id, page id, version, uploaded inside the window)
        self.files: list[tuple[str, str, int, bool]] = []
        self.asked: list[str] = []

    def page(self, id_: str, *, version: int = 37, space: str = "OPS", edited: bool = False):
        self.pages[id_] = (space, version, edited)

    def file(
        self, page: str, *, id_: str = "81920301", version: int = 3, uploaded: bool = True
    ):
        self.files.append((id_, page, version, uploaded))

    def _page(self, id_: str) -> dict:
        space, version, _ = self.pages[id_]
        return {
            "id": id_,
            "type": "page",
            "title": f"page {id_}",
            "version": {"number": version, "when": "2026-08-01T16:02:00.000Z"},
        }

    def _matched(self, cql: str, expand: str) -> list[dict]:
        if cql == f"type = attachment AND {WINDOW}":
            return [
                {
                    "id": id_,
                    "type": "attachment",
                    "title": "escalation-matrix.png",
                    "version": {"number": version},
                    **(
                        {"container": {"id": page, "type": "page"}}
                        if "container" in expand
                        else {}
                    ),
                }
                for id_, page, version, uploaded in self.files
                if uploaded
            ]
        in_scope = [id_ for id_, (space, _, _) in self.pages.items() if space == "OPS"]
        if cql == f"({QUERY}) AND type = page AND {WINDOW}":
            return [self._page(id_) for id_ in in_scope if self.pages[id_][2]]
        named = re.fullmatch(rf"\({re.escape(QUERY)}\) AND type = page AND id in \((.+)\)", cql)
        if named:
            ids = named.group(1).split(", ")
            return [self._page(id_) for id_ in in_scope if id_ in ids]
        if cql == f"({QUERY}) AND type = page":
            return [self._page(id_) for id_ in in_scope]
        raise AssertionError(f"a question Data Center was not expected to be asked: {cql}")

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/rest/api/content/search", request.url
            query = parse_qs(request.url.query.decode())
            cql = query["cql"][0]
            self.asked.append(cql)
            matched = self._matched(cql, query.get("expand", [""])[0])
            start, limit = int(query.get("start", ["0"])[0]), int(query["limit"][0])
            results = matched[start : start + limit]
            links = {"base": BASE, "context": ""}
            if start + limit < len(matched):
                links["next"] = f"/rest/api/content/search?start={start + limit}&limit={limit}"
            return httpx.Response(
                200, json={"results": results, "size": len(results), "_links": links}
            )

        return httpx.MockTransport(handle)


def listed(server: Confluence, since: datetime | None = SINCE) -> list[tuple[str, str | None]]:
    connector = ConfluenceConnector(base_url=BASE, query=QUERY, transport=server.transport())
    return [(ref.key, ref.remote_version) for ref in connector.list(since)]


class TestAWindowedListingFindsPagesWhoseFilesChanged:
    """R1.22 — the pages whose files changed, as the source's query scopes them."""

    def test_a_page_whose_file_was_uploaded_again_is_listed(self):
        """Row 1: the one where the page did not move and its file did."""
        server = Confluence()
        server.page(PAGE)
        server.file(PAGE)

        assert listed(server) == [(PAGE, "v37")]
        assert server.asked[1] == f"type = attachment AND {WINDOW}"
        assert server.asked[2] == f"({QUERY}) AND type = page AND id in ({PAGE})"

    def test_a_page_edited_and_given_a_new_file_is_listed_once(self):
        """Row 2: the one found by both questions, and yielded by one."""
        server = Confluence()
        server.page(PAGE, version=38, edited=True)
        server.file(PAGE)

        assert listed(server) == [(PAGE, "v38")]
        assert not any(" id in (" in cql for cql in server.asked)

    def test_sixty_pages_with_new_files_are_asked_about_fifty_at_a_time(self):
        """Row 3: the one where the pages need two `id in` questions."""
        server = Confluence()
        pages = [str(81920200 + n) for n in range(60)]
        for n, id_ in enumerate(pages):
            server.page(id_)
            server.file(id_, id_=str(81930000 + n))

        keys = [key for key, _ in listed(server)]

        assert sorted(keys) == pages
        named = [cql for cql in server.asked if " id in (" in cql]
        assert [cql.count(",") + 1 for cql in named] == [50, 10]

    def test_a_new_file_on_a_page_the_query_does_not_match_lists_nothing(self):
        """Counter-example (row 4): the one in another space."""
        server = Confluence()
        server.page(PAGE)
        server.page("81990001", space="ENG")
        server.file("81990001")

        assert listed(server) == []

    def test_a_complete_listing_asks_one_question(self):
        """Counter-example (row 5): the one where every page is listed anyway."""
        server = Confluence()
        server.page(PAGE)
        server.file(PAGE)

        assert listed(server, since=None) == [(PAGE, "v37")]
        assert server.asked == [f"({QUERY}) AND type = page"]

    def test_a_removed_file_lists_nothing(self):
        """Counter-example (row 6): the one search cannot see; a complete listing settles it."""
        server = Confluence()
        server.page(PAGE)
        server.file(PAGE, uploaded=False)

        assert listed(server) == []
        assert not any(" id in (" in cql for cql in server.asked)
