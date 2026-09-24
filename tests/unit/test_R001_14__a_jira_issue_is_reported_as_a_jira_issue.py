"""R1.14 — a Jira issue is reported as `application/vnd.dossier.jira-issue+json`.

A media type chooses a converter (R8.3), and the pair is the whole type: a
converter claiming `application/json` would claim every JSON document any source
ever holds. The issue is labelled with what wrote it. A file the issue carries is
still what Jira says that file is (R2.16).

Every request goes through an `httpx.MockTransport` answering with
`tests/fixtures/jira/INC-4821.json`. No socket is opened.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from dossier.domain.conversion import JIRA_ISSUE, media_type_for
from dossier.infrastructure.connectors.jira import JiraConnector

JIRA = "https://jira.example.internal"
ISSUE = Path(__file__).resolve().parents[1] / "fixtures" / "jira" / "INC-4821.json"


def _jira() -> JiraConnector:
    payload = ISSUE.read_bytes()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/2/issue/INC-4821":
            return httpx.Response(
                200, content=payload, headers={"content-type": "application/json;charset=UTF-8"}
            )
        if request.url.path == "/secure/attachment/10001/report.pdf":
            return httpx.Response(
                200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}
            )
        return httpx.Response(404)

    return JiraConnector(
        base_url=JIRA, query="project = INC", transport=httpx.MockTransport(handle)
    )


class TestAJiraIssueIsReportedAsAJiraIssue:
    """R1.14 — the label names what wrote the payload."""

    def test_an_issue_is_labelled_a_jira_issue(self):
        """Row 1: the one where `INC-4821` is fetched."""
        fetched = _jira().fetch("INC-4821")

        assert fetched.media_type == "application/vnd.dossier.jira-issue+json"
        assert fetched.media_type == JIRA_ISSUE

    def test_the_payload_is_the_bytes_jira_sent(self):
        """Row 1, second half: the label changes, the bytes do not (R1.2)."""
        assert _jira().fetch("INC-4821").payload == ISSUE.read_bytes()

    def test_a_file_the_issue_carries_is_what_jira_says_it_is(self):
        """Counter-example, row 2: the one where the attachment is a PDF."""
        assert _jira().fetch("INC-4821/report.pdf").media_type == "application/pdf"

    def test_a_json_file_in_a_folder_is_still_json(self):
        """Counter-example, row 3: the one where only a filename is known (R2.16)."""
        assert media_type_for("export.json") == "application/json"
