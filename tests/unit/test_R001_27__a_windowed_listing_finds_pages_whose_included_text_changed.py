"""R1.27 — a windowed listing also lists each page the query matches that
includes a page changed in the window.

An edit to an included page leaves the including page's `lastmodified` where it
was, so a windowed `type = page` search leaves it out. A Data Center 9.2.21 in
Docker showed it on 2026-09-27. R1.26 already asks, at every sync, which of the
query's pages include others and when what they include last changed. So an
including page is listed when anything it draws in, directly or through another
page, changed at or after the window's floor (R1.4). The included page need not
be in the query's scope.

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
# `SINCE` widened by a day, as R1.15 row 2 asks it: the floor is 2026-08-05 09:00.
WINDOW = 'lastmodified >= "2026-08-05 09:00"'
INSIDE = "2026-08-06T08:00:00.000Z"
BEFORE = "2026-07-01T16:02:00.000Z"
PAGE = "81920114"
TITLE = "OPS-114 Incident escalation procedure"
CONTACTS = "Escalation contacts"


def include(title: str, space: str | None = None) -> str:
    key = f' ri:space-key="{space}"' if space else ""
    return (
        '<ac:structured-macro ac:name="include" ac:schema-version="1">'
        f'<ac:parameter ac:name=""><ac:link><ri:page{key} ri:content-title="{title}" />'
        "</ac:link></ac:parameter></ac:structured-macro>"
    )


class Confluence:
    """Pages, each last edited before the window or inside it."""

    def __init__(self) -> None:
        # id -> (space, title, version, when, storage)
        self.pages: dict[str, tuple[str, str, int, str, str]] = {}
        self.asked: list[str] = []

    def page(self, id_: str, title: str, *, space="OPS", version=37, when=BEFORE, body=""):
        self.pages[id_] = (space, title, version, when, f"<p>{title}</p>{body}")

    def _json(self, id_: str) -> dict:
        space, title, version, when, storage = self.pages[id_]
        return {
            "id": id_,
            "type": "page",
            "title": title,
            "version": {"number": version, "when": when},
            "space": {"key": space},
            "body": {"storage": {"value": storage}},
        }

    def _matched(self, cql: str) -> list[dict]:
        in_scope = [id_ for id_, page in self.pages.items() if page[0] == "OPS"]
        if cql == f"({QUERY}) AND type = page":
            return [self._json(id_) for id_ in in_scope]
        if cql == f"({QUERY}) AND type = page AND {WINDOW}":
            return [self._json(id_) for id_ in in_scope if self.pages[id_][3] == INSIDE]
        if cql == f"type = attachment AND {WINDOW}":
            return []
        if cql == f'({QUERY}) AND type = page AND macro in (include, "excerpt-include")':
            return [
                self._json(id_) for id_ in in_scope if 'ac:name="include"' in self.pages[id_][4]
            ]
        named = re.fullmatch(r'type = page AND space = "([^"]+)" AND title in \((.+)\)', cql)
        if named:
            titles = re.findall(r'"([^"]*)"', named[2])
            return [
                self._json(id_)
                for id_, (space, title, *_) in self.pages.items()
                if space == named[1] and title in titles
            ]
        raise AssertionError(f"a question Data Center was not expected to be asked: {cql}")

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/rest/api/content/search", request.url
            cql = parse_qs(request.url.query.decode())["cql"][0]
            self.asked.append(cql)
            results = self._matched(cql)
            return httpx.Response(
                200, json={"results": results, "size": len(results), "_links": {"base": BASE}}
            )

        return httpx.MockTransport(handle)


def listed(server: Confluence, since: datetime | None = SINCE) -> list[tuple[str, str | None]]:
    connector = ConfluenceConnector(base_url=BASE, query=QUERY, transport=server.transport())
    return [(ref.key, ref.remote_version) for ref in connector.list(since)]


class TestAWindowedListingFindsPagesWhoseIncludedTextChanged:
    """R1.27 — an including page is listed when what it draws in changed."""

    def test_a_page_whose_included_page_was_edited_is_listed_once(self):
        """Row 1: the one where `Escalation contacts` moved and `81920114` did not."""
        server = Confluence()
        server.page(PAGE, TITLE, body=include(CONTACTS))
        server.page("81920130", CONTACTS, version=3, when=INSIDE)

        found = dict(listed(server))

        assert found[PAGE].startswith("v37+i")
        assert [key for key, _ in listed(server)].count(PAGE) == 1

    def test_an_included_page_in_another_space_lists_the_including_one_alone(self):
        """Row 2: the one where the edited page is outside `space = OPS`."""
        server = Confluence()
        server.page(PAGE, TITLE, body=include(CONTACTS, "ENG"))
        server.page("81990130", CONTACTS, space="ENG", version=3, when=INSIDE)

        assert [key for key, _ in listed(server)] == [PAGE]

    def test_nothing_it_includes_changed_so_it_is_not_listed(self):
        """Counter-example (row 3): the one where the included page is as it was."""
        server = Confluence()
        server.page(PAGE, TITLE, body=include(CONTACTS))
        server.page("81920130", CONTACTS, version=2, when=BEFORE)

        assert listed(server) == []

    def test_a_complete_listing_lists_every_page_once(self):
        """Counter-example (row 4): the one where every page is listed anyway."""
        server = Confluence()
        server.page(PAGE, TITLE, body=include(CONTACTS))
        server.page("81920130", CONTACTS, version=3, when=INSIDE)

        keys = [key for key, _ in listed(server, since=None)]

        assert sorted(keys) == ["81920114", "81920130"]
        assert dict(listed(server, since=None))[PAGE].startswith("v37+i")
