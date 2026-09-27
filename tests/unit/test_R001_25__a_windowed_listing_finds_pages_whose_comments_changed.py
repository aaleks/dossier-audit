"""R1.25 — with `comments: true`, a windowed listing also lists each page the
query matches whose comments changed in the window.

A comment, or a reply, leaves its page's `lastmodified` where it was: a Data
Center 9.2.21 in Docker showed it on 2026-09-27, and found the comment with
`type = comment AND lastmodified >= …`, naming the page as its container, reply
or not. So R1.22's second question asks for files and comments together:
`type in (attachment, comment) AND lastmodified >= <floor>`. A removed comment is
absent from search, as a removed file is.

Every request goes through an `httpx.MockTransport`. No socket is opened.
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
    """`81920114` at version 37, edited before the window, and what is on it."""

    def __init__(self) -> None:
        # (id, type, version, changed inside the window, a reply)
        self.content: list[tuple[str, str, int, bool]] = []
        self.asked: list[str] = []

    def comment(self, id_: str, *, changed: bool = True) -> None:
        self.content.append((id_, "comment", 1, changed))

    def file(self, id_: str = "81920301") -> None:
        self.content.append((id_, "attachment", 3, True))

    def _on_the_page(
        self, kinds: tuple[str, ...], *, changed_only: bool, expand: str
    ) -> list[dict]:
        return [
            {
                "id": id_,
                "type": kind,
                "version": {"number": number},
                **(
                    {"container": {"id": PAGE, "type": "page"}} if "container" in expand else {}
                ),
            }
            for id_, kind, number, changed in self.content
            if kind in kinds and (changed or not changed_only)
        ]

    def _matched(self, cql: str, expand: str) -> list[dict]:
        page = {"id": PAGE, "type": "page", "version": {"number": 37}}
        if cql == f"type = attachment AND {WINDOW}":
            return self._on_the_page(("attachment",), changed_only=True, expand=expand)
        if cql == f"type in (attachment, comment) AND {WINDOW}":
            return self._on_the_page(
                ("attachment", "comment"), changed_only=True, expand=expand
            )
        if cql == f"({QUERY}) AND type = page AND {WINDOW}":
            return []
        if re.fullmatch(rf"\({re.escape(QUERY)}\) AND type = page AND id in \({PAGE}\)", cql):
            return [page]
        if cql == f"type = comment AND container in ({PAGE})":
            return self._on_the_page(("comment",), changed_only=False, expand=expand)
        raise AssertionError(f"a question Data Center was not expected to be asked: {cql}")

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/rest/api/content/search", request.url
            query = parse_qs(request.url.query.decode())
            cql = query["cql"][0]
            self.asked.append(cql)
            results = self._matched(cql, query.get("expand", [""])[0])
            return httpx.Response(
                200, json={"results": results, "size": len(results), "_links": {"base": BASE}}
            )

        return httpx.MockTransport(handle)


def listed(server: Confluence, *, comments: bool = True) -> list[tuple[str, str | None]]:
    connector = ConfluenceConnector(
        base_url=BASE, query=QUERY, comments=comments, transport=server.transport()
    )
    return [(ref.key, ref.remote_version) for ref in connector.list(SINCE)]


class TestAWindowedListingFindsPagesWhoseCommentsChanged:
    """R1.25 — the pages whose comments changed, as the source's query scopes them."""

    def test_a_page_given_a_comment_is_listed_once_with_its_comments_marker(self):
        """Row 1: the one where the page did not move and a comment on it did."""
        server = Confluence()
        server.comment("81920501")

        ((key, marker),) = listed(server)

        assert key == PAGE
        assert marker.startswith("v37+c")
        assert f"type in (attachment, comment) AND {WINDOW}" in server.asked

    def test_a_page_given_a_reply_is_listed(self):
        """Row 2: the one where the reply names the page as its container."""
        server = Confluence()
        server.comment("81920501", changed=False)
        server.comment("81920502")

        assert [key for key, _ in listed(server)] == [PAGE]

    def test_without_comments_the_question_is_about_files_alone(self):
        """Counter-example (row 3): the one where `comments:` is off."""
        server = Confluence()
        server.comment("81920501")

        assert listed(server, comments=False) == []
        assert f"type = attachment AND {WINDOW}" in server.asked
        assert not any("comment" in cql for cql in server.asked)

    def test_a_removed_comment_lists_nothing(self):
        """Counter-example (row 4): the one search cannot see; a complete listing settles it."""
        server = Confluence()
        server.comment("81920501", changed=False)

        assert listed(server) == []
