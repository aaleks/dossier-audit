"""R8.19 — `confluence-page-markdown` converts a page to a note of what a person reads.

What is proved here is row 2, the reason the connector and the converter exist:
a page synced from Confluence is converted, a stage reads it, and a sentence
quoted from its body is grounded. Before them, nothing could sync a Confluence
space at all.

Run through the CLI because the claim needs every link in the chain: the real
Confluence connector listing, fetching and labelling a page (R1.15–R1.18), a
converter claiming that label, and grounding finding the quote in what the
converter wrote (R6.4). Only Confluence itself is played: an
`httpx.MockTransport` answering with `tests/fixtures/confluence/`, a page and its
attachment listing in the shape a real Confluence Data Center 9.2 sends. No
socket is opened.

The page carries `escalation-matrix.png`, which is its own document (R1.18) and
converts as an image does (R8.10). The model is a fake that quotes from the page
and abstains on anything else it is shown, so the order the run asks in does not
matter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import register_connector
from tests.pipelines import write_pipeline

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
SOURCE = "procedures-confluence"
CONFLUENCE = "https://confluence.example.internal"

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PAGE = FIXTURES / "confluence" / "81920114.json"
ATTACHMENTS = FIXTURES / "confluence" / "81920114-attachments.json"
# What `escalation-matrix.png` holds. Any PNG: the file is its own document,
# and what it shows is not what this rule is about.
MATRIX = FIXTURES / "documents" / "images" / "INC-5720-checkout-latency-postmortem.png"

KEY = "81920114"
TITLE = "OPS-114 Incident escalation procedure"
# Spec 008 R8.19 row 2: a sentence from the page's body, as a person reads it.
STEP = "Page the incident commander within 15 minutes"
# Row 3: the version's message. The payload holds it word for word; the note
# is the page a person reads, and a person reading the page never sees it.
MACHINERY = "Rota link updated"


def _confluence():
    """A Confluence Data Center holding `OPS-114` and the file it carries."""
    import httpx

    page = PAGE.read_bytes()
    held = json.loads(page)

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/content/search":
            listed = {
                "id": held["id"],
                "type": "page",
                "status": "current",
                "title": held["title"],
                "version": {
                    "number": held["version"]["number"],
                    "when": held["version"]["when"],
                },
            }
            return httpx.Response(
                200,
                json={
                    "results": [listed],
                    "start": 0,
                    "limit": 50,
                    "size": 1,
                    "_links": {"base": CONFLUENCE, "context": ""},
                },
            )
        if path == f"/rest/api/content/{KEY}/child/attachment":
            return httpx.Response(
                200,
                content=ATTACHMENTS.read_bytes(),
                headers={"content-type": "application/json"},
            )
        if path == f"/rest/api/content/{KEY}":
            return httpx.Response(
                200, content=page, headers={"content-type": "application/json"}
            )
        if path == f"/download/attachments/{KEY}/escalation-matrix.png":
            return httpx.Response(
                200, content=MATRIX.read_bytes(), headers={"content-type": "image/png"}
            )
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def _connect(monkeypatch) -> None:
    """The shipped Confluence connector, reaching the Confluence above instead of a socket."""
    from dossier.infrastructure.connectors.confluence import (
        ConfluenceConnector,
        ConfluenceKeys,
    )

    def built(config, *, workspace):
        return ConfluenceConnector(
            base_url=config.options["url"],
            query=config.options["query"],
            transport=_confluence(),
        )

    register_connector(monkeypatch, "confluence", built, keys=ConfluenceKeys)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _use(monkeypatch, client) -> None:
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


class _Reader:
    """A model that quotes `span` from the page and abstains on anything else."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self, span: str) -> None:
        self.span = span
        self.call_count = 0

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.call_count += 1
        if TITLE in prompt:
            quoted = {
                "field": "root_cause",
                "value": f"{STEP}.",
                "source": {"document": KEY, "span": self.span},
            }
            return json.dumps({"document": KEY, "fields": [quoted]})
        abstained = {"field": "root_cause", "value": None, "reason": "not in this document"}
        return json.dumps({"document": f"{KEY}/escalation-matrix.png", "fields": [abstained]})


@pytest.fixture
def confluence_workspace(workspace: Path, monkeypatch) -> Path:
    """`procedures-confluence`: one page in a Confluence, and the file it carries."""
    pytest.importorskip("PIL", reason="the attachment is a PNG: needs dossier[pdf]")
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        f"  - id: {SOURCE}\n"
        "    type: confluence\n"
        f"    url: {CONFLUENCE}\n"
        "    query: space = OPS\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, steps=["extract"], sources=[SOURCE])
    return workspace


def _audit(workspace: Path, monkeypatch, span: str):
    """Sync, convert and run the workspace, with a model quoting `span`."""
    _connect(monkeypatch)
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    converted = _cli(workspace, monkeypatch, "convert", PIPELINE)
    assert converted.exit_code == 0, converted.output

    model = _Reader(span)
    _use(monkeypatch, model)
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    assert model.call_count >= 1
    return result


class TestAConfluencePageIsAuditedEndToEnd:
    """R8.19 — a page converts to a note a stage reads and a span is grounded in."""

    def test_a_sentence_quoted_from_the_body_is_grounded(
        self, confluence_workspace: Path, monkeypatch
    ):
        """Row 2: the one where a Confluence space is audited at all.

        No finding is the grounded outcome: an ungrounded field is reported as
        one (R6.16), and scored incorrect before any comparison (R7.4).
        """
        result = _audit(confluence_workspace, monkeypatch, STEP)

        assert "finding" not in result.output, result.output
        written = next((confluence_workspace / "runs").rglob(f"extract/{KEY}.json"))
        fields = json.loads(written.read_text(encoding="utf-8"))["fields"]
        assert fields[0]["value"] == f"{STEP}."

    def test_the_version_message_the_payload_holds_is_not_in_the_note(
        self, confluence_workspace: Path, monkeypatch
    ):
        """Counter-example, row 3: the one where the quote is machinery.

        The version's message is in the payload Confluence sent, word for word.
        A span quoted from it is ungrounded because the note left it out, which
        keeps a model from finding a plausible quote in the JSON nobody reads.
        """
        result = _audit(confluence_workspace, monkeypatch, MACHINERY)

        assert "1 finding(s)" in result.output, result.output
