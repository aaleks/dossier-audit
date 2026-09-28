"""R8.16 — `jira-issue-markdown` converts an issue to a note of what a person reads.

What is proved here is row 5, the reason the converter exists: an issue synced
from Jira is converted, a stage reads it, and a figure quoted from its
description is grounded. Before it, `dossier convert` refused every issue with
`nothing converts ('application/json', 'markdown')`, so a Jira source could be
synced and never audited.

Run through the CLI because the claim needs every link in the chain: the real
Jira connector labelling what it fetched (R1.14), a converter claiming that
label, and grounding finding the quote in what the converter wrote (R6.4). Only
Jira itself is played: an `httpx.MockTransport` answering with
`tests/fixtures/jira/INC-4821.json`, an issue in the shape a real Jira Server
sends, attachment included. No socket is opened.

The model is a fake. It is asked twice -- once for the issue and once for the
file it carries, which is its own document (R1.6) -- and answers by which one it
was shown, so the order the run asks in does not matter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import register_connector
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
SOURCE = "incidents-jira"
JIRA = "https://jira.example.internal"

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ISSUE = FIXTURES / "jira" / "INC-4821.json"
# What `report.pdf` holds. Any PDF with a text layer: the attachment is its own
# document, and what it says is not what this rule is about.
REPORT = FIXTURES / "documents" / "scans" / "PLAY-2001-terminal-scan.pdf"

KEY = "INC-4821"
ATTACHMENT = f"{KEY}/report.pdf"
# Spec 008 R8.16 row 5: a figure from the description, as a person reads it.
LOSS = "total exposure CHF 48'200"
# Row 6: a custom field's value, which the payload holds and the note must not.
CUSTOM_FIELD = "Mitigation owner: payments-oncall rota 7"


def _jira():
    """A Jira Server holding `INC-4821` and the file it carries."""
    import httpx

    issue = ISSUE.read_bytes()

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/2/search":
            listed = json.loads(issue)
            return httpx.Response(
                200,
                json={
                    "startAt": 0,
                    "maxResults": 50,
                    "total": 1,
                    "issues": [
                        {
                            "key": listed["key"],
                            "fields": {
                                "updated": listed["fields"]["updated"],
                                "attachment": listed["fields"]["attachment"],
                            },
                        }
                    ],
                },
            )
        if path == f"/rest/api/2/issue/{KEY}":
            return httpx.Response(
                200, content=issue, headers={"content-type": "application/json;charset=UTF-8"}
            )
        if path == "/secure/attachment/10001/report.pdf":
            return httpx.Response(
                200, content=REPORT.read_bytes(), headers={"content-type": "application/pdf"}
            )
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def _connect(monkeypatch) -> None:
    """The shipped Jira connector, reaching the Jira above instead of a socket."""
    from dossier.infrastructure.connectors.jira import JiraConnector, JiraKeys

    def built(config, *, workspace):
        return JiraConnector(
            base_url=config.options["url"],
            query=config.options["query"],
            transport=_jira(),
        )

    register_connector(monkeypatch, "jira", built, keys=JiraKeys)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _use(monkeypatch, client) -> None:
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


class _Reader:
    """A model that quotes `span` from the issue and abstains on its attachment."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self, span: str) -> None:
        self.span = span
        self.call_count = 0

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.call_count += 1
        if "Card payments declined at checkout" in prompt:
            quoted = {
                "field": "loss_amount",
                "value": 48200.00,
                "currency": "CHF",
                "source": {"document": KEY, "span": self.span},
            }
            return json.dumps({"document": KEY, "fields": [quoted]})
        abstained = {"field": "loss_amount", "value": None, "reason": "the file states no loss"}
        return json.dumps({"document": ATTACHMENT, "fields": [abstained]})


@pytest.fixture
def jira_workspace(workspace: Path, monkeypatch) -> Path:
    """`incidents-jira`: one issue in a Jira, and the file it carries."""
    pytest.importorskip("pypdfium2", reason="the attachment is a PDF: needs dossier[pdf]")
    _connect(monkeypatch)
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        f"  - id: {SOURCE}\n"
        "    type: jira\n"
        f"    url: {JIRA}\n"
        "    query: project = INC\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, steps=["extract"], sources=[SOURCE])
    return workspace


def _audit(workspace: Path, monkeypatch, span: str):
    """Sync, convert and run the workspace, with a model quoting `span`."""
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    converted = _cli(workspace, monkeypatch, "convert", PIPELINE)
    assert converted.exit_code == 0, converted.output

    model = _Reader(span)
    _use(monkeypatch, model)
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    assert model.call_count == 2
    return result


class TestAJiraIssueIsAuditedEndToEnd:
    """R8.16 — an issue converts to a note a stage reads and a span is grounded in."""

    def test_a_figure_quoted_from_the_description_is_grounded(
        self, jira_workspace: Path, monkeypatch
    ):
        """Row 5: the one where a Jira source is audited at all.

        No finding is the grounded outcome: an ungrounded field is reported as
        one (R6.16), and scored incorrect before any comparison (R7.4).
        """
        result = _audit(jira_workspace, monkeypatch, LOSS)

        assert "finding" not in result.output, result.output
        written = next((jira_workspace / "runs").rglob(f"extract/{KEY}.json"))
        fields = json.loads(written.read_text(encoding="utf-8"))["fields"]
        assert fields[0]["value"] == 48200.00

    def test_a_custom_field_the_payload_holds_is_not_in_the_note(
        self, jira_workspace: Path, monkeypatch
    ):
        """Counter-example, row 6: the one where the quote is machinery.

        `customfield_10042` is in the payload Jira sent, word for word. A span
        quoted from it is ungrounded because the note left it out -- which is
        what keeps a model from finding a plausible quote in forty kilobytes of
        payload nobody reads.
        """
        result = _audit(jira_workspace, monkeypatch, CUSTOM_FIELD)

        assert "1 finding(s)" in result.output, result.output
