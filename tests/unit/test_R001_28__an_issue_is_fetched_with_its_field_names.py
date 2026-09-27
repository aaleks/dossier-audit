"""R1.28 — a Jira issue is fetched with `expand=names,schema`.

A custom field arrives as `customfield_10050` in an issue's `fields`. What a
person calls it, and what kind of value it holds, come only when the fetch asks:
`names` maps each field to its name, and `schema` to its type. The listing asks
for no expansion, because `names` and `schema` would then come once for every
issue listed.

Every request goes through an `httpx.MockTransport` playing a Data Center that,
as the one read on 2026-09-27 did, adds `names` and `schema` to an issue only
when `expand` asks for them. No socket is opened.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from dossier.infrastructure.connectors.jira import JiraConnector

JIRA = "https://jira.example.internal"
ISSUE = Path(__file__).resolve().parents[1] / "fixtures" / "jira" / "INC-4821.json"

NAMES = {"customfield_10050": "Root cause"}
SCHEMA = {"customfield_10050": {"type": "string", "custom": "textfield", "customId": 10050}}


class DataCenter:
    """A Data Center recording what each request asked, as path and query."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, list[str]]]] = []
        self.sent: bytes = b""

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            query = parse_qs(request.url.query.decode())
            self.requests.append((request.url.path, query))
            if request.url.path == "/rest/api/2/search":
                return httpx.Response(
                    200,
                    json={
                        "startAt": 0,
                        "total": 1,
                        "issues": [
                            {
                                "key": "INC-4821",
                                "fields": {"updated": "2026-08-06T08:41:00.000+0000"},
                            }
                        ],
                    },
                )
            if request.url.path == "/rest/api/2/issue/INC-4821":
                issue = json.loads(ISSUE.read_bytes())
                if query.get("expand") == ["names,schema"]:
                    issue = {**issue, "names": NAMES, "schema": SCHEMA}
                self.sent = json.dumps(issue).encode("utf-8")
                return httpx.Response(
                    200, content=self.sent, headers={"content-type": "application/json"}
                )
            if request.url.path == "/secure/attachment/10001/report.pdf":
                return httpx.Response(
                    200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}
                )
            return httpx.Response(404)

        return httpx.MockTransport(handle)


def _jira(server: DataCenter) -> JiraConnector:
    return JiraConnector(base_url=JIRA, query="project = INC", transport=server.transport())


class TestAnIssueIsFetchedWithItsFieldNames:
    """R1.28 — the fetch asks for names and schema; nothing else does."""

    def test_an_issue_is_fetched_asking_for_names_and_schema(self):
        """Row 1: the one where `INC-4821` is fetched.

        One request, at the issue's route, asking `expand=names,schema`; the
        payload is the bytes the server sent, and those hold `names` and
        `schema` because they were asked for.
        """
        server = DataCenter()

        item = _jira(server).fetch("INC-4821")

        assert server.requests == [("/rest/api/2/issue/INC-4821", {"expand": ["names,schema"]})]
        assert item.payload == server.sent
        payload = json.loads(item.payload)
        assert payload["names"] == NAMES
        assert payload["schema"] == SCHEMA

    def test_the_listing_asks_for_no_expansion(self):
        """Counter-example, row 2: the one where the source is listed.

        The search asks for the two fields a listing needs and no `expand`:
        `names` and `schema` would otherwise come once for every issue listed
        (R1.13).
        """
        server = DataCenter()

        list(_jira(server).list(None))

        ((path, query),) = server.requests
        assert path == "/rest/api/2/search"
        assert query["fields"] == ["updated,attachment"]
        assert "expand" not in query

    def test_a_file_is_fetched_as_before(self):
        """Counter-example, row 3: the one where `INC-4821/report.pdf` is fetched.

        The file's bytes, as before. A file has no fields, so nothing asked on
        its way expands any.
        """
        server = DataCenter()

        item = _jira(server).fetch("INC-4821/report.pdf")

        assert item.payload == b"%PDF-1.7"
        assert [path for path, _ in server.requests] == [
            "/rest/api/2/issue/INC-4821",
            "/secure/attachment/10001/report.pdf",
        ]
        assert server.requests[0][1] == {"fields": ["attachment"]}
        assert all("expand" not in query for _, query in server.requests)
