"""R2.26 — what a connector's fetch asks for is part of the source configuration hash.

A connector may declare what its fetch asks for beyond an item's address:
`fetch_asks`. It joins R2.3's projection in the source configuration hash, so a
connector that starts asking for more fetches every item it holds again, once,
and the next sync fetches only what changed. A connector that declares nothing
hashes as it did before this rule.

Rows 1 and 2 are claims about what a sync does, so they are measured through
`sync_source` over a real ledger and store, against the Jira connector talking
to an `httpx.MockTransport` that vouches -- correctly -- that no issue moved. It
adds `names` and `schema` to an issue only when `expand` asks for them, as the
Data Center read on 2026-09-27 did. Rows 3 and 4 are claims about the hash.
No socket is opened.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from dossier.application.sync import SourceReport, sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.sync import source_config_hash
from dossier.infrastructure.connectors.folder import FolderConnector
from dossier.infrastructure.connectors.jira import JiraConnector
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

JIRA = "https://jira.example.internal"
QUERY = "project = INC"
UPDATED = "2026-08-05T09:12:00.000+0000"
FIRST = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
SECOND = FIRST + timedelta(days=1)
THIRD = SECOND + timedelta(days=1)

# The source configuration hash of a source declaring no `fields`, as it was
# computed before this rule: SHA-256 of `{"fields":null}`. Written out rather
# than recomputed, so that "byte-identical" is a claim about the bytes and not
# about whichever formula the test shares with the code.
BEFORE_NO_FIELDS = "f0613db6af9ddfd5cac98e6f1a5c2088d194a23911b0e0a91828e308151de82b"

ISSUES = ("INC-4821", "INC-4822")


def jira_source(fields: list[str] | None = None) -> SourceConfig:
    return SourceConfig(
        id="incidents-jira", type="jira", fields=fields, options={"url": JIRA, "query": QUERY}
    )


class DataCenter:
    """Two issues last updated at `UPDATED`, and nothing attached to either.

    Records the path and query of every request, so a test can count the issue
    fetches apart from the listing and the attachment lookups.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            query = parse_qs(request.url.query.decode())
            self.requests.append((request.url.path, query))
            if request.url.path == "/rest/api/2/search":
                return httpx.Response(
                    200,
                    json={
                        "startAt": 0,
                        "total": len(ISSUES),
                        "issues": [issue(k) for k in ISSUES],
                    },
                )
            key = request.url.path.removeprefix("/rest/api/2/issue/")
            if key in ISSUES:
                body = issue(key)
                if query.get("expand") == ["names,schema"]:
                    body |= {
                        "names": {"summary": "Summary", "updated": "Updated"},
                        "schema": {"summary": {"type": "string", "system": "summary"}},
                    }
                return httpx.Response(200, json=body)
            return httpx.Response(404)

        return httpx.MockTransport(handle)

    def fetched(self) -> list[str]:
        """The issues fetched whole: an issue's route asked for more than its files."""
        return [
            path.removeprefix("/rest/api/2/issue/")
            for path, query in self.requests
            if path.startswith("/rest/api/2/issue/") and query.get("fields") != ["attachment"]
        ]


def issue(key: str) -> dict:
    return {
        "key": key,
        "fields": {"summary": f"{key} summary", "updated": UPDATED, "attachment": []},
    }


def sync(workspace: Path, connector, config: SourceConfig, *, now: datetime) -> SourceReport:
    with Ledger(workspace) as ledger:
        return sync_source(
            config=config,
            connector=connector,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
        )


def recorded_hash(workspace: Path, source_id: str) -> str | None:
    with Ledger(workspace) as ledger:
        return ledger.config_hash(source_id)


@pytest.fixture
def synced_before(tmp_path: Path) -> DataCenter:
    """`incidents-jira` synced once, its ledger holding the hash from before this rule.

    Which is what a workspace synced before its connector asked for
    `expand=names,schema` holds: the projection's hash, and nothing about what
    the fetch asked.
    """
    server = DataCenter()
    connector = JiraConnector(base_url=JIRA, query=QUERY, transport=server.transport())
    sync(tmp_path, connector, jira_source(), now=FIRST)
    with Ledger(tmp_path) as ledger:
        ledger.set_config_hash("incidents-jira", BEFORE_NO_FIELDS)
    server.requests.clear()
    return server


class TestAChangeToWhatAFetchAsksFetchesEverythingOnce:
    """R2.26 — what the fetch asks joins the projection in the hash."""

    def test_asking_for_more_fetches_every_issue_again(
        self, tmp_path: Path, synced_before: DataCenter
    ):
        """Row 1: the one where `incidents-jira` was synced before the connector asked.

        Neither issue's `updated` moved, so without this rule neither would be
        fetched (R2.1). The recorded hash answered a fetch that asked for less,
        so both are fetched again, and the hash of what is asked now is recorded.
        That the fetch asks for `names` and `schema` is R1.28's; the stand-in
        adds them only when asked, so the new snapshot holding them shows the
        fetch that asked.
        """
        connector = JiraConnector(
            base_url=JIRA, query=QUERY, transport=synced_before.transport()
        )

        report = sync(tmp_path, connector, jira_source(), now=SECOND)

        assert report.fetched == len(ISSUES)
        assert sorted(synced_before.fetched()) == sorted(ISSUES)
        assert JiraConnector.fetch_asks == "expand=names,schema"
        assert recorded_hash(tmp_path, "incidents-jira") == source_config_hash(
            jira_source(), fetch_asks=JiraConnector.fetch_asks
        )
        assert recorded_hash(tmp_path, "incidents-jira") != BEFORE_NO_FIELDS
        with Ledger(tmp_path) as ledger:
            held = ledger.row("incidents-jira", "INC-4821")
        assert "names" in json.loads(SnapshotStore(tmp_path).get(held.snapshot))

    def test_the_sync_after_that_fetches_nothing(
        self, tmp_path: Path, synced_before: DataCenter
    ):
        """Row 2: the one where the next sync finds the hash it recorded.

        Once, and not again: nothing changed, so `0 fetched`.
        """
        connector = JiraConnector(
            base_url=JIRA, query=QUERY, transport=synced_before.transport()
        )
        sync(tmp_path, connector, jira_source(), now=SECOND)
        synced_before.requests.clear()

        report = sync(tmp_path, connector, jira_source(), now=THIRD)

        assert report.fetched == 0
        assert synced_before.fetched() == []

    def test_a_connector_that_declares_nothing_hashes_as_it_did(self, tmp_path: Path):
        """Counter-example, row 3: the one where `incidents-manual` is a folder.

        The folder connector declares no `fetch_asks`, and its source hashes to
        the bytes it hashed to before this rule. A folder reads every file on
        every sync, having no marker to skip one by (R2.1); what it is spared is
        a re-evaluation, which it would be under any other hash.
        """
        (tmp_path / "manual").mkdir()
        (tmp_path / "manual" / "audit-note.pdf").write_bytes(b"%PDF-1.7 audit note")
        manual = SourceConfig(id="incidents-manual", type="folder", options={"path": "manual"})
        folder = FolderConnector(tmp_path / "manual")

        assert getattr(folder, "fetch_asks", "") == ""
        assert source_config_hash(manual) == BEFORE_NO_FIELDS
        assert source_config_hash(manual, fetch_asks="") == BEFORE_NO_FIELDS

        sync(tmp_path, folder, manual, now=FIRST)
        report = sync(tmp_path, folder, manual, now=SECOND)

        assert recorded_hash(tmp_path, "incidents-manual") == BEFORE_NO_FIELDS
        assert report.snapshots_written == 0

    def test_reordered_fields_still_hash_the_same(self):
        """Counter-example, row 4: the one where `fields` is reordered on `incidents-jira`.

        What the fetch asks joins the projection; it does not make the
        projection a list. The hash does not change, as R2.3 row 2 says.
        """
        asks = JiraConnector.fetch_asks

        assert source_config_hash(
            jira_source(["key", "fields"]), fetch_asks=asks
        ) == source_config_hash(jira_source(["fields", "key"]), fetch_asks=asks)
        assert source_config_hash(
            jira_source(["key", "fields"]), fetch_asks=asks
        ) != source_config_hash(jira_source(["key", "fields"]))
