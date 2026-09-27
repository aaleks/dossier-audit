"""R1.24 — with `comments: true`, a page's marker moves when a comment on it is
added, edited or removed.

A comment is content of its own. Adding, editing or removing one leaves the page
at its version, and its `lastmodified` where it was: a Data Center 9.2.21 in
Docker showed it on 2026-09-27. So the page's marker is its version, followed by
`+c` and the first twelve hex digits of the SHA-256 of its comments' `<id>:v<n>`,
sorted and joined by newlines. A page with no comment keeps its version alone.

The listing asks which comments its pages carry once for every 50 pages, with
`type = comment AND container in (…)`. That server answered it, and named each
comment's page as its container, reply or not, when `expand=container` asked.

Every request goes through an `httpx.MockTransport`. No socket is opened.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs

import httpx

from dossier.domain.confluence import commented_version
from dossier.infrastructure.connectors.confluence import ConfluenceConnector

BASE = "https://confluence.example.internal"
QUERY = "space = OPS"
PAGE = "81920114"


def digest(*markers: str) -> str:
    return hashlib.sha256("\n".join(sorted(markers)).encode()).hexdigest()[:12]


class Confluence:
    """Pages at version 37, and the comments on them, answered 50 at a time."""

    def __init__(self) -> None:
        self.pages: list[str] = []
        # page id -> {comment id: version}
        self.comments: dict[str, dict[str, int]] = {}
        self.asked: list[str] = []

    def page(self, id_: str, **comments: int) -> None:
        self.pages.append(id_)
        self.comments[id_] = {key.removeprefix("c"): number for key, number in comments.items()}

    def _matched(self, cql: str, expand: str) -> list[dict]:
        if cql == f'({QUERY}) AND type = page AND macro in (include, "excerpt-include")':
            # No page here includes another (R1.26).
            return []
        if cql == f"({QUERY}) AND type = page":
            return [
                {"id": id_, "type": "page", "version": {"number": 37}} for id_ in self.pages
            ]
        named = re.fullmatch(r"type = comment AND container in \((.+)\)", cql)
        if named:
            return [
                {
                    "id": comment,
                    "type": "comment",
                    "version": {"number": number},
                    **(
                        {"container": {"id": page, "type": "page"}}
                        if "container" in expand
                        else {}
                    ),
                }
                for page in named.group(1).split(", ")
                for comment, number in self.comments.get(page, {}).items()
            ]
        raise AssertionError(f"a question Data Center was not expected to be asked: {cql}")

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/rest/api/content/search", request.url
            query = parse_qs(request.url.query.decode())
            cql = query["cql"][0]
            self.asked.append(cql)
            matched = self._matched(cql, query.get("expand", [""])[0])
            start, limit = int(query.get("start", ["0"])[0]), int(query["limit"][0])
            links = {"base": BASE, "context": ""}
            if start + limit < len(matched):
                links["next"] = f"/rest/api/content/search?start={start + limit}&limit={limit}"
            results = matched[start : start + limit]
            return httpx.Response(
                200, json={"results": results, "size": len(results), "_links": links}
            )

        return httpx.MockTransport(handle)

    def comment_searches(self) -> list[str]:
        return [cql for cql in self.asked if cql.startswith("type = comment")]


def markers(server: Confluence, *, comments: bool = True) -> dict[str, str | None]:
    connector = ConfluenceConnector(
        base_url=BASE, query=QUERY, comments=comments, transport=server.transport()
    )
    return {ref.key: ref.remote_version for ref in connector.list()}


class TestAPagesMarkerMovesWithItsComments:
    """R1.24 — `v37+c` and a digest of the page's comments."""

    def test_a_page_with_comments_is_marked_by_them(self):
        """Row 1: the one where `81920114` carries a comment at version 2 and a reply."""
        server = Confluence()
        server.page(PAGE, c81920501=2, c81920502=1)

        assert markers(server) == {PAGE: f"v37+c{digest('81920501:v2', '81920502:v1')}"}

    def test_an_edited_comment_moves_the_marker(self):
        """Row 2: the one where the reply is edited and the page is not."""
        server = Confluence()
        server.page(PAGE, c81920501=2, c81920502=1)
        before = markers(server)[PAGE]

        server.comments[PAGE]["81920502"] = 2

        assert markers(server)[PAGE] not in (before, "v37")

    def test_a_removed_comment_moves_the_marker(self):
        """Row 3: the one where the reply is removed."""
        server = Confluence()
        server.page(PAGE, c81920501=2, c81920502=1)
        before = markers(server)[PAGE]

        del server.comments[PAGE]["81920502"]

        assert markers(server)[PAGE] == f"v37+c{digest('81920501:v2')}" != before

    def test_the_comments_of_120_pages_are_asked_for_50_pages_at_a_time(self):
        """Row 4: the one where three searches cover every page listed."""
        server = Confluence()
        for n in range(120):
            server.page(str(81920200 + n), **{f"c{81930000 + n}": 1})

        listed = markers(server)

        assert [cql.count(",") + 1 for cql in server.comment_searches()] == [50, 50, 20]
        assert listed["81920200"] == f"v37+c{digest('81930000:v1')}"

    def test_a_page_with_no_comment_keeps_its_version(self):
        """Counter-example (row 5): the one where `comments:` is on and finds none."""
        server = Confluence()
        server.page(PAGE)

        assert markers(server) == {PAGE: "v37"}

    def test_without_comments_the_marker_is_the_version_and_nothing_is_searched(self):
        """Counter-example (row 6): the one where `comments:` is off."""
        server = Confluence()
        server.page(PAGE, c81920501=2)

        assert markers(server, comments=False) == {PAGE: "v37"}
        assert server.comment_searches() == []


class TestTheCommentedMarker:
    """R1.24 — the composition, decided in the domain."""

    def test_the_version_and_a_digest_of_the_comments_sorted(self):
        forward = commented_version("v37", ["81920501:v2", "81920502:v1"])

        assert forward == f"v37+c{digest('81920501:v2', '81920502:v1')}"
        assert commented_version("v37", ["81920502:v1", "81920501:v2"]) == forward

    def test_no_comment_is_the_version_alone(self):
        assert commented_version("v37", []) == "v37"

    def test_a_marker_nobody_can_vouch_for_is_none(self):
        assert commented_version(None, ["81920501:v2"]) is None
        assert commented_version("v37", ["81920501:v2", None]) is None
