"""R1.15 — a Confluence source lists the pages its CQL query matches, and nothing
else the query matches.

The connector asks `GET /rest/api/content/search` with the source's `query` and
`type = page` added to it, paging by `start` and `limit` until a page of results
names no `next`. A CQL query matches comments and attachments as readily as
pages; an attachment is reached through its page (R1.18), and the rest are not
held.

Every request goes through an `httpx.MockTransport` playing Confluence Data
Center, which reads `type = page` in the CQL as Confluence does. No socket is
opened.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx

from dossier.infrastructure.connectors.confluence import ConfluenceConnector

BASE = "https://confluence.example.internal"
QUERY = "space = OPS"
SINCE = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


def page(n: int) -> dict:
    return {
        "id": str(81920114 + n),
        "type": "page",
        "status": "current",
        "title": f"OPS-{114 + n}",
        "version": {"number": 1, "when": "2026-08-05T16:02:00.000Z"},
    }


class Confluence:
    """Data Center answering `content/search`, 50 results at a time.

    Without `type = page` in the CQL, the space's comment and attachment match
    too, as they would on a real server.
    """

    def __init__(self, pages: int) -> None:
        self.pages = [page(n) for n in range(pages)]
        self.others = [
            {"id": "81920500", "type": "comment", "status": "current", "title": "Re: OPS-114"},
            {"id": "81920301", "type": "attachment", "status": "current", "title": "m.png"},
        ]
        self.asked: list[dict[str, list[str]]] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path != "/rest/api/content/search":
                return httpx.Response(404)
            query = parse_qs(request.url.query.decode())
            self.asked.append(query)
            cql = query["cql"][0]
            if cql.startswith("type = attachment") or "macro in" in cql:
                # The files changed in a window (R1.22), and the pages that
                # include another (R1.26): none, here.
                matched: list[dict] = []
            else:
                matched = self.pages if "type = page" in cql else self.pages + self.others
            start, limit = int(query.get("start", ["0"])[0]), int(query["limit"][0])
            results = matched[start : start + limit]
            links = {"base": BASE, "context": ""}
            if start + limit < len(matched):
                links["next"] = f"/rest/api/content/search?start={start + limit}&limit={limit}"
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

        return httpx.MockTransport(handle)


def connector(server: Confluence) -> ConfluenceConnector:
    return ConfluenceConnector(base_url=BASE, query=QUERY, transport=server.transport())


class TestAConfluenceSourceListsThePagesItsQueryMatches:
    """R1.15 — every page the query matches, a page of results at a time."""

    def test_every_matching_page_is_listed_across_three_pages_of_results(self):
        """Example 1: the one where 120 pages come back 50 at a time."""
        server = Confluence(pages=120)

        listed = list(connector(server).list(None))

        listing = [q for q in server.asked if "macro in" not in q["cql"][0]]
        assert [ref.key for ref in listed] == [p["id"] for p in server.pages]
        assert [q["start"] for q in listing] == [["0"], ["50"], ["100"]]
        assert {q["cql"][0] for q in listing} == {"(space = OPS) AND type = page"}

    def test_since_narrows_the_query_by_the_widened_window(self):
        """Example 2: the one where the window is widened by a day, as Jira's is."""
        server = Confluence(pages=3)

        list(connector(server).list(SINCE))

        asked = server.asked[0]
        assert asked["cql"] == [
            '(space = OPS) AND type = page AND lastmodified >= "2026-08-05 09:00"'
        ]

    def test_a_comment_and_an_attachment_the_query_matches_are_not_listed(self):
        """Counter-example, row 3: the one where `space = OPS` matches more than pages."""
        server = Confluence(pages=2)

        listed = list(connector(server).list(None))

        assert [ref.key for ref in listed] == ["81920114", "81920115"]

    def test_the_connector_says_its_listings_may_be_partial(self):
        """Counter-example, row 4: the one where `since` narrows the CQL (R1.11)."""
        assert ConfluenceConnector.lists_everything is False
