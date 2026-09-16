"""R1.1 — a connector never writes to the source system.

`dossier` reads. No connector issues a create, update, delete or transition
against the system it reads from, including status-only side effects such as
marking a page as viewed.

The claim is about HTTP verbs, so it needs a connector that speaks HTTP: the
folder connector cannot violate this rule and cannot prove it either. Every
request the Jira connector makes goes through an `httpx.MockTransport` that
records it, and the assertion is over the methods -- which is the one thing that
cannot be satisfied by accident.

No socket is opened: the transport answers everything.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from dossier.domain.pipeline import SourceConfig
from dossier.infrastructure.connectors.jira import JiraConnector
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

BASE = "https://jira.example.internal"
QUERY = "project = INC AND updated >= -30d"
TOKEN = "jira-pat-4f1a-do-not-print"

ISSUE = "INC-4821"
REPORT = f"{ISSUE}/report.pdf"
REPORT_BYTES = b"%PDF-1.4\nthe incident report\n"

SOURCE = SourceConfig(id="incidents-jira", type="jira", options={"query": QUERY})


def issue_json(key: str) -> dict:
    """One issue as Jira renders it, with its attachment metadata."""
    return {
        "key": key,
        "fields": {
            "summary": "Batch failed",
            "updated": "2026-08-05T16:02:00.000+0000",
            "attachment": [
                {
                    "id": "10021",
                    "filename": "report.pdf",
                    "created": "2026-08-05T16:05:00.000+0000",
                    "mimeType": "application/pdf",
                    "content": f"{BASE}/secure/attachment/10021/report.pdf",
                }
            ],
        },
    }


class Recorder:
    """Jira, answering reads and remembering every method it was asked for."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append((request.method, str(request.url)))
            path = request.url.path

            if path.endswith("/rest/api/2/search"):
                return httpx.Response(
                    200,
                    json={
                        "startAt": 0,
                        "maxResults": 50,
                        "total": 1,
                        "issues": [issue_json(ISSUE)],
                    },
                )
            if path.endswith(f"/rest/api/2/issue/{ISSUE}"):
                return httpx.Response(200, json=issue_json(ISSUE))
            if "/secure/attachment/" in path:
                return httpx.Response(
                    200, content=REPORT_BYTES, headers={"content-type": "application/pdf"}
                )
            return httpx.Response(404, json={"errorMessages": [f"no route for {path}"]})

        return httpx.MockTransport(handle)

    @property
    def methods(self) -> set[str]:
        return {method for method, _ in self.requests}


def connector(recorder: Recorder) -> JiraConnector:
    """The Jira connector over a recording transport, holding a token it must not leak."""
    return JiraConnector(
        base_url=BASE, query=QUERY, token=TOKEN, transport=recorder.transport()
    )


def sync(workspace: Path, source_connector):
    from dossier.application.sync import sync_source

    with Ledger(workspace) as ledger:
        return sync_source(
            config=SOURCE,
            connector=source_connector,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC),
        )


class TestConnectorNeverWritesToTheSource:
    """R1.1 — every request is a read."""

    def test_a_full_sync_issues_only_get_requests(self, tmp_path: Path):
        """Example 1: the one where `incidents-jira` is synced against a recorder.

        Every request is `GET`. A sync that listed, fetched and stored an issue
        and its attachment had every opportunity to write, and took none of them.
        """
        recorder = Recorder()

        report = sync(tmp_path, connector(recorder))

        assert recorder.requests, "the sync reached the source"
        assert recorder.methods == {"GET"}
        assert report.failed == ()
        with Ledger(tmp_path) as ledger:
            assert {row.key for row in ledger.rows(SOURCE.id)} == {ISSUE, REPORT}

    def test_asking_for_attachments_issues_only_get_requests(self, tmp_path: Path):
        """Example 2: the one where `attachments("INC-4821")` is asked on its own.

        Listing what an issue carries is a read of the issue. Jira's own UI marks
        things as seen; a connector that reached such a route would be writing
        while believing it was looking.
        """
        recorder = Recorder()
        jira = connector(recorder)

        carried = list(jira.attachments(ISSUE))

        assert [ref.key for ref in carried] == [REPORT]
        assert recorder.methods == {"GET"}

    def test_the_payload_is_what_the_source_returned(self, tmp_path: Path):
        """The reason the rule matters: what is stored is what was read (R1.2).

        A connector that wrote to the source could change the very bytes it is
        about to snapshot, and every hash downstream would describe an artefact
        of the audit rather than the incident.
        """
        recorder = Recorder()
        jira = connector(recorder)

        attachment = jira.fetch(REPORT)

        assert attachment.payload == REPORT_BYTES
        assert attachment.media_type == "application/pdf"
        assert json.loads(jira.fetch(ISSUE).payload)["key"] == ISSUE
        assert recorder.methods == {"GET"}

    def test_updating_the_local_ledger_reaches_no_source_at_all(self, tmp_path: Path):
        """Counter-example (row 3): the one where the ledger row is updated.

        Allowed, and not a write to the source system in any sense: the ledger is
        dossier's own state, on dossier's own disk. Nothing leaves the machine,
        which is exactly why the rule is about requests rather than about writes
        in general.
        """
        recorder = Recorder()
        sync(tmp_path, connector(recorder))
        after_sync = len(recorder.requests)

        with Ledger(tmp_path) as ledger:
            ledger.touch(SOURCE.id, ISSUE, seen_at=datetime(2026, 8, 7, 9, 0, 0, tzinfo=UTC))
            ledger.set_watermark(SOURCE.id, datetime(2026, 8, 7, 9, 0, 0, tzinfo=UTC))

        assert len(recorder.requests) == after_sync
        assert recorder.methods == {"GET"}
