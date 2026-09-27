"""R1.26 — a page that includes another page's text has a marker that moves with
what it includes.

`include` and `excerpt-include` draw another page's text into a page, and the
including page's own version does not move when that text does. A Data Center
9.2.21 in Docker showed it on 2026-09-27: `Escalation contacts` was edited to
version 2, and the page including it stayed at version 1 while its
`export_view` changed. So the marker is the page's version, then `+i` and twelve
hex digits of the SHA-256 of each included page's `<id>:v<n>`, sorted.

Which pages use either macro, CQL answers (`macro in (include,
"excerpt-include")`, checked on that server). Which page each names is written
only in the storage format, as that server stored it:
`<ri:page ri:space-key="OPS" ri:content-title="Escalation contacts" />`. Those
pages are then asked for by space and title.

Every request goes through an `httpx.MockTransport`. No socket is opened.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs

import httpx

from dossier.domain.confluence import included_pages, including_version
from dossier.infrastructure.connectors.confluence import ConfluenceConnector

BASE = "https://confluence.example.internal"
QUERY = "space = OPS"
PAGE = "81920114"
TITLE = "OPS-114 Incident escalation procedure"
CONTACTS = "Escalation contacts"
ROTA = "On-call rota"


def digest(*markers: str) -> str:
    return hashlib.sha256("\n".join(sorted(markers)).encode()).hexdigest()[:12]


def include(title: str, space: str | None = None, macro: str = "include") -> str:
    """An include as Confluence stores it, as the local Data Center did."""
    key = f' ri:space-key="{space}"' if space else ""
    return (
        f'<ac:structured-macro ac:name="{macro}" ac:schema-version="1">'
        f'<ac:parameter ac:name=""><ac:link><ri:page{key} ri:content-title="{title}" />'
        "</ac:link></ac:parameter></ac:structured-macro>"
    )


class Confluence:
    """Pages in spaces, some drawing others' text into them."""

    def __init__(self) -> None:
        # id -> (space, title, version, storage)
        self.pages: dict[str, tuple[str, str, int, str]] = {}
        self.asked: list[str] = []

    def page(
        self, id_: str, title: str, *, version: int = 37, space: str = "OPS", body: str = ""
    ):
        self.pages[id_] = (space, title, version, f"<p>{title}</p>{body}")

    def _json(self, id_: str, expand: str) -> dict:
        space, title, version, storage = self.pages[id_]
        return {
            "id": id_,
            "type": "page",
            "title": title,
            "version": {"number": version, "when": "2026-08-01T16:02:00.000Z"},
            "space": {"key": space},
            **({"body": {"storage": {"value": storage}}} if "body.storage" in expand else {}),
        }

    def _matched(self, cql: str, expand: str) -> list[dict]:
        in_scope = [id_ for id_, page in self.pages.items() if page[0] == "OPS"]
        if cql == f"({QUERY}) AND type = page":
            return [self._json(id_, expand) for id_ in in_scope]
        if cql == f'({QUERY}) AND type = page AND macro in (include, "excerpt-include")':
            return [
                self._json(id_, expand)
                for id_ in in_scope
                if re.search(r'ac:name="(include|excerpt-include)"', self.pages[id_][3])
            ]
        named = re.fullmatch(r'type = page AND space = "([^"]+)" AND title in \((.+)\)', cql)
        if named:
            titles = [
                t.replace('\\"', '"') for t in re.findall(r'"((?:[^"\\]|\\.)*)"', named[2])
            ]
            return [
                self._json(id_, expand)
                for id_, (space, title, _, _) in self.pages.items()
                if space == named[1] and title in titles
            ]
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


def markers(server: Confluence) -> dict[str, str | None]:
    connector = ConfluenceConnector(base_url=BASE, query=QUERY, transport=server.transport())
    return {ref.key: ref.remote_version for ref in connector.list()}


class TestAPagesMarkerMovesWithWhatItIncludes:
    """R1.26 — `v37+i` and a digest of what the page draws in."""

    def test_a_page_including_another_is_marked_by_it(self):
        """Row 1: the one where `81920114` includes `Escalation contacts` at version 2."""
        server = Confluence()
        server.page(PAGE, TITLE, body=include(CONTACTS))
        server.page("81920130", CONTACTS, version=2)

        assert markers(server)[PAGE] == f"v37+i{digest('81920130:v2')}"

    def test_an_edit_to_the_included_page_moves_the_including_ones_marker(self):
        """Row 2: the one where `Escalation contacts` is edited and `81920114` is not."""
        server = Confluence()
        server.page(PAGE, TITLE, body=include(CONTACTS, "OPS"))
        server.page("81920130", CONTACTS, version=2)
        before = markers(server)[PAGE]

        server.page("81920130", CONTACTS, version=3)

        assert markers(server)[PAGE] == f"v37+i{digest('81920130:v3')}" != before

    def test_what_an_included_page_includes_moves_the_marker_too(self):
        """Row 3: the one where the rota, two inclusions away, is edited."""
        server = Confluence()
        server.page(PAGE, TITLE, body=include(CONTACTS))
        server.page(
            "81920130", CONTACTS, version=2, body=include(ROTA, macro="excerpt-include")
        )
        server.page("81920131", ROTA, version=5)
        before = markers(server)[PAGE]

        server.page("81920131", ROTA, version=6)

        after = markers(server)[PAGE]
        assert after == f"v37+i{digest('81920130:v2', '81920131:v6')}" != before

    def test_an_include_naming_no_page_counts_as_missing(self):
        """Row 4: the one where `ENG` has no page by that title."""
        server = Confluence()
        server.page(PAGE, TITLE, body=include(CONTACTS, "ENG"))

        assert markers(server)[PAGE] == f"v37+i{digest('missing:ENG/Escalation contacts')}"

    def test_a_page_including_nothing_keeps_its_version(self):
        """Counter-example (row 5): the one where nothing is drawn in."""
        server = Confluence()
        server.page(PAGE, TITLE)

        assert markers(server) == {PAGE: "v37"}

    def test_two_pages_including_each_other_are_each_counted_once(self):
        """Counter-example (row 6): the one where the included page includes `81920114` back."""
        server = Confluence()
        server.page(PAGE, TITLE, body=include(CONTACTS))
        server.page("81920130", CONTACTS, version=2, body=include(TITLE))

        assert markers(server) == {
            PAGE: f"v37+i{digest('81920130:v2')}",
            "81920130": f"v2+i{digest(f'{PAGE}:v37')}",
        }


class TestWhatAPageIncludes:
    """R1.26 — the decisions over the storage format, made in the domain."""

    def test_an_include_names_its_space_or_the_pages_own(self):
        storage = include(CONTACTS) + include(ROTA, "ENG", macro="excerpt-include")

        assert included_pages(storage, space="OPS") == [("ENG", ROTA), ("OPS", CONTACTS)]

    def test_a_link_to_a_page_is_not_an_include(self):
        storage = f'<p><ac:link><ri:page ri:content-title="{CONTACTS}" /></ac:link></p>'

        assert included_pages(storage, space="OPS") == []

    def test_a_title_is_read_as_the_storage_escapes_it(self):
        storage = include("Contacts &amp; rota")

        assert included_pages(storage, space="OPS") == [("OPS", "Contacts & rota")]

    def test_the_marker_is_the_version_and_a_sorted_digest(self):
        assert including_version("v37", ["81920131:v6", "81920130:v2"]) == (
            f"v37+i{digest('81920130:v2', '81920131:v6')}"
        )
        assert including_version("v37", []) == "v37"
        assert including_version(None, ["81920130:v2"]) is None
