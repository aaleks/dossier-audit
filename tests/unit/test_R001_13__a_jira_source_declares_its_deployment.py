"""R1.13 — a Jira source declares its deployment, and the listing route follows it.

Data Center lists at `/rest/api/2/search`, paged by `startAt` against `total`.
Cloud has retired that route and lists at `/rest/api/2/search/jql`, paged by the
`nextPageToken` each page hands back until one says `isLast`. Fetching an issue
is the same on both. Nothing is inferred from the hostname.

Every request goes through an `httpx.MockTransport` playing one deployment or
the other. No socket is opened.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from dossier.config.load import ConfigError, load_sources
from dossier.infrastructure.connectors.jira import JiraConnector, JiraKeys

DATACENTER = "https://jira.example.internal"
CLOUD = "https://example.atlassian.net"
QUERY = "project = INC AND type = Incident"
SINCE = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)

ISSUE = "INC-4821"


def issue_json(key: str) -> dict:
    return {"key": key, "fields": {"updated": "2026-07-30T09:14:00.000+0000", "attachment": []}}


def keys(count: int) -> list[str]:
    return [f"INC-{4821 + n}" for n in range(count)]


class DataCenter:
    """A Data Center answering `search` by offset, `total` issues in all."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append((request.url.path, parse_qs(request.url.query.decode())))
            if request.url.path == "/rest/api/2/search":
                start = int(parse_qs(request.url.query.decode())["startAt"][0])
                page = keys(self.total)[start : start + 50]
                return httpx.Response(
                    200,
                    json={
                        "startAt": start,
                        "total": self.total,
                        "issues": [issue_json(k) for k in page],
                    },
                )
            if request.url.path == f"/rest/api/2/issue/{ISSUE}":
                return httpx.Response(200, json=issue_json(ISSUE))
            return httpx.Response(410, json={"errorMessages": ["gone"]})

        return httpx.MockTransport(handle)


class Cloud:
    """A Cloud answering `search/jql` by token: three pages, the last saying so."""

    PAGES = {None: ("p2", keys(2)), "p2": ("p3", ["INC-4901"]), "p3": (None, ["INC-4902"])}

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            query = parse_qs(request.url.query.decode())
            self.requests.append((request.url.path, query))
            if request.url.path == "/rest/api/2/search/jql":
                token = query.get("nextPageToken", [None])[0]
                following, page = self.PAGES[token]
                body: dict = {
                    "issues": [issue_json(k) for k in page],
                    "isLast": following is None,
                }
                if following:
                    body["nextPageToken"] = following
                return httpx.Response(200, json=body)
            if request.url.path == f"/rest/api/2/issue/{ISSUE}":
                return httpx.Response(200, json=issue_json(ISSUE))
            return httpx.Response(410, json={"errorMessages": ["gone"]})

        return httpx.MockTransport(handle)


def write_sources(tmp_path: Path, *, deployment: str | None) -> Path:
    path = tmp_path / "sources.yaml"
    declared = f"    deployment: {deployment}\n" if deployment else ""
    path.write_text(
        f"sources:\n  - id: incidents-jira\n    type: jira\n    url: {DATACENTER}\n"
        f"    query: {QUERY}\n{declared}",
        encoding="utf-8",
    )
    return path


class TestAJiraSourceDeclaresItsDeployment:
    """R1.13 — the route follows the declaration, never the hostname."""

    @pytest.mark.parametrize("deployment", ["datacenter", None])
    def test_datacenter_pages_by_offset_until_total(self, tmp_path: Path, deployment):
        """Example 1: the one where 420 issues come in nine offset pages.

        Declared, or left absent: the key defaults to Data Center. 420
        `ItemRef`s, as R1.3 row 2 promises, and `startAt` walks 0, 50, ... 400.
        """
        (source,) = load_sources(
            write_sources(tmp_path, deployment=deployment), connectors={"jira": JiraKeys}
        )
        server = DataCenter(total=420)
        connector = JiraConnector(
            base_url=DATACENTER,
            query=QUERY,
            deployment=source.options.get("deployment", "datacenter"),
            transport=server.transport(),
        )

        refs = list(connector.list(None))

        assert [ref.key for ref in refs] == keys(420)
        assert {path for path, _ in server.requests} == {"/rest/api/2/search"}
        assert [int(q["startAt"][0]) for _, q in server.requests] == list(range(0, 420, 50))

    def test_cloud_pages_by_the_token_each_page_hands_back(self):
        """Example 2: the one where Cloud answers in three pages.

        The first request carries no token, the second and third carry the one
        the page before handed back, and the listing stops at the page that
        says `isLast` -- there is no `total` to count against.
        """
        server = Cloud()
        connector = JiraConnector(
            base_url=CLOUD, query=QUERY, deployment="cloud", transport=server.transport()
        )

        refs = list(connector.list(None))

        assert [ref.key for ref in refs] == [*keys(2), "INC-4901", "INC-4902"]
        assert [path for path, _ in server.requests] == ["/rest/api/2/search/jql"] * 3
        assert [q.get("nextPageToken") for _, q in server.requests] == [None, ["p2"], ["p3"]]
        assert all(q["fields"] == ["updated,attachment"] for _, q in server.requests)

    def test_cloud_fetches_an_issue_at_the_same_route(self):
        """Example 3: the one where only the listing differs.

        `INC-4821` is fetched at `/rest/api/2/issue/INC-4821` on Cloud as on
        Data Center; the deployment changes where a listing is asked for and
        nothing else. What the fetch asks is the same as well: its field names
        and types (R1.28).
        """
        server = Cloud()
        connector = JiraConnector(
            base_url=CLOUD, query=QUERY, deployment="cloud", transport=server.transport()
        )

        item = connector.fetch(ISSUE)

        assert item.key == ISSUE
        assert server.requests == [(f"/rest/api/2/issue/{ISSUE}", {"expand": ["names,schema"]})]

    def test_an_unknown_deployment_is_refused_at_load_time(self, tmp_path: Path):
        """Counter-example (row 4): the one written as `deployment: server`.

        Refused by the connector's declaration when `sources.yaml` is read
        (R1.10), naming the key and the two values it takes.
        """
        with pytest.raises(ConfigError) as error:
            load_sources(
                write_sources(tmp_path, deployment="server"), connectors={"jira": JiraKeys}
            )

        message = str(error.value)
        assert "deployment" in message
        assert "datacenter" in message and "cloud" in message

    def test_since_narrows_the_query_the_same_way_on_both(self):
        """Counter-example (row 5): the one where `since` is given on either deployment.

        The same widened `updated >=` clause (R1.4) reaches both routes: the
        deployment decides where the query goes, never what it says.
        """
        datacenter, cloud = DataCenter(total=1), Cloud()
        on_datacenter = JiraConnector(
            base_url=DATACENTER, query=QUERY, transport=datacenter.transport()
        )
        on_cloud = JiraConnector(
            base_url=CLOUD, query=QUERY, deployment="cloud", transport=cloud.transport()
        )

        list(on_datacenter.list(SINCE))
        list(on_cloud.list(SINCE))

        (jql_datacenter,) = datacenter.requests[0][1]["jql"]
        (jql_cloud,) = cloud.requests[0][1]["jql"]
        assert jql_datacenter == jql_cloud
        assert jql_datacenter.startswith(f"{QUERY} AND updated >= ")
