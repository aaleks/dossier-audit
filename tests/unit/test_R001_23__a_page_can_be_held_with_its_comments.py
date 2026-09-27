"""R1.23 — with `comments: true`, a page's payload also holds its comments, replies included.

Only `child/comment?depth=all` returns a reply: expanded on the page,
`children.comment` is the top-level comments, 25 at most. That was read against
a Data Center 9.2.21 in Docker on 2026-09-27, and `81920114-comments.json` is
that server's answer with the fixtures' content in it.

The payload is one JSON object holding each answer as Confluence sent it:
`{"page":<the page>,"comments":[<each answer>]}`. It keeps the page's media
type, so the converter that claims a page claims it (R8.30).

Every request goes through an `httpx.MockTransport`. No socket is opened.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from dossier.config.load import ConfigError, load_sources
from dossier.domain.conversion import CONFLUENCE_PAGE
from dossier.infrastructure.connectors.confluence import ConfluenceConnector, ConfluenceKeys

BASE = "https://confluence.example.internal"
PAGE = "81920114"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "confluence"
SENT = (FIXTURE / f"{PAGE}.json").read_bytes()
COMMENTS = (FIXTURE / f"{PAGE}-comments.json").read_bytes()
THREAD = f"/rest/api/content/{PAGE}/child/comment"


def answer(results: list[dict], *, start: int, more: bool) -> bytes:
    links = {"base": BASE, "context": ""}
    if more:
        links["next"] = f"{THREAD}?depth=all&start={start + len(results)}"
    return json.dumps(
        {
            "results": results,
            "start": start,
            "limit": 50,
            "size": len(results),
            "_links": links,
        },
        separators=(",", ":"),
    ).encode()


def comment(n: int) -> dict:
    return {"id": str(81920600 + n), "type": "comment", "version": {"number": 1}}


class Confluence:
    """Data Center holding `OPS-114`, and the comments on it, answered 50 at a time."""

    def __init__(self, answers: list[bytes] | None = None) -> None:
        self.answers = [COMMENTS] if answers is None else answers
        self.asked: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.asked.append(request)
            if request.url.path == f"/rest/api/content/{PAGE}":
                return httpx.Response(200, content=SENT)
            if request.url.path == THREAD:
                start = int(request.url.params.get("start", "0"))
                starts = [0, *(50 * n for n in range(1, len(self.answers)))]
                return httpx.Response(200, content=self.answers[starts.index(start)])
            raise AssertionError(f"not a route Data Center was asked here: {request.url}")

        return httpx.MockTransport(handle)

    def comment_requests(self) -> list[httpx.Request]:
        return [request for request in self.asked if request.url.path == THREAD]


def connector(server: Confluence, **keys) -> ConfluenceConnector:
    return ConfluenceConnector(
        base_url=BASE, query="space = OPS", transport=server.transport(), **keys
    )


class TestAPageCanBeHeldWithItsComments:
    """R1.23 — `comments: true` holds each page with its comments, as Confluence sent them."""

    def test_a_page_is_held_with_its_comment_and_the_reply_to_it(self):
        """Row 1: the one where the payload holds the page and the thread, byte for byte."""
        server = Confluence()

        held = connector(server, comments=True).fetch(PAGE)

        assert held.payload == b'{"page":' + SENT + b',"comments":[' + COMMENTS + b"]}"
        assert held.media_type == CONFLUENCE_PAGE
        (asked,) = server.comment_requests()
        assert asked.url.params["depth"] == "all"
        assert "body.export_view" in asked.url.params["expand"]
        replies = [
            c["id"]
            for answer_ in json.loads(held.payload)["comments"]
            for c in answer_["results"]
            if c["ancestors"]
        ]
        assert replies == ["81920502"]

    def test_sixty_comments_are_held_in_the_two_answers_they_came_in(self):
        """Row 2: the one where the thread takes two answers, held in the order asked."""
        first = answer([comment(n) for n in range(50)], start=0, more=True)
        second = answer([comment(n) for n in range(50, 60)], start=50, more=False)
        server = Confluence([first, second])

        held = connector(server, comments=True).fetch(PAGE)

        assert (
            held.payload
            == b'{"page":' + SENT + b',"comments":[' + first + b"," + second + b"]}"
        )
        assert [r.url.params["start"] for r in server.comment_requests()] == ["0", "50"]

    def test_without_comments_the_page_is_held_as_sent(self):
        """Counter-example (row 3): the one where no comment is asked for."""
        server = Confluence()

        held = connector(server).fetch(PAGE)

        assert held.payload == SENT
        assert server.comment_requests() == []

    def test_a_value_comments_does_not_take_is_refused_at_load_time(self, tmp_path: Path):
        """Counter-example (row 4): the one where `comments: maybe` is asked for."""
        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n"
            "  - id: procedures-confluence\n"
            "    type: confluence\n"
            f"    url: {BASE}\n"
            "    query: space = OPS\n"
            "    comments: maybe\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors={"confluence": ConfluenceKeys})

        assert "comments" in str(error.value)
