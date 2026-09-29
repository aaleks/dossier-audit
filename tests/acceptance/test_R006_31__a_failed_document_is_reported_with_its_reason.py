"""R6.31 — `dossier run` reports a failed document on one line naming why it
failed.

The slice's acceptance rule, proved through the CLI. R6.32 says what a
validation failure's reason is, and R6.33 what a page-by-page document's is;
either could be MET while the line a person reads still said nothing. Before
this, the line was `    extract failed on INC-4822`, and why was printed
nowhere with MLflow off.

The incidents are markdown in the folder source `incidents-manual`, so their
keys carry the extension (`INC-4822.md`), as R3.17's do. `INC-4830` is the
PDF postmortem read page by page (`_fixtures.md`). The model is a
`FakeModelClient` answering in the order it is asked, and it **counts calls**.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
SOURCE = "incidents-manual"
NOT_JSON = "not JSON at all"
EMPTY = "every input it reads is empty: documents"
INVALID = "no valid output after 2 attempts: Invalid JSON: expected ident at line 1 column 2"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
TEXT = {
    "INC-4821.md": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822.md": "# INC-4822\n\nThe payment gateway timed out for two hours.\n",
}


def _nothing(document: str) -> str:
    return json.dumps({"document": document, "fields": [abstains(f) for f in FIELDS]})


def _run(workspace: Path, monkeypatch, files: dict[str, str], replies: list[str], **pipeline):
    """A folder source holding `files`, synced and run; the result and the model."""
    from tests.fakes import FakeModelClient

    import dossier.cli.bootstrap as cli

    inbox = workspace / "inbox" / "manual"
    inbox.mkdir(parents=True)
    for name, text in files.items():
        if text is None:
            shutil.copy(FIXTURES / "postmortems" / "pdf" / name, inbox / name)
        else:
            (inbox / name).write_text(text, encoding="utf-8")
    convert = pipeline.pop("convert", "")
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: folder\n    path: inbox/manual/\n{convert}",
        encoding="utf-8",
    )
    write_pipeline(workspace, name=PIPELINE, sources=[SOURCE], **pipeline)
    model = FakeModelClient(responses=replies)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)
    for command in ("sync", "convert"):
        assert _cli(workspace, monkeypatch, command, PIPELINE).exit_code == 0
    return _cli(workspace, monkeypatch, "run", PIPELINE), model


class TestAFailedDocumentIsReportedWithItsReason:
    """R6.31 — `    {step} failed on {document}: {reason}`, one line."""

    def test_an_answer_that_is_not_json_says_so(self, workspace: Path, monkeypatch):
        """Row 1 — the one that answered prose on both attempts."""
        result, model = _run(
            workspace, monkeypatch, {"INC-4822.md": TEXT["INC-4822.md"]}, [NOT_JSON, NOT_JSON]
        )

        assert result.exit_code == 1, result.output
        assert model.call_count == 2
        assert f"    extract failed on INC-4822.md: {INVALID}" in result.stderr.splitlines(), (
            result.stderr
        )

    def test_an_empty_note_says_its_input_was_empty(self, workspace: Path, monkeypatch):
        """Row 2 — the one with nothing in it (R6.29)."""
        files = {"INC-4821.md": TEXT["INC-4821.md"], "handover-note.md": ""}
        result, _ = _run(workspace, monkeypatch, files, [_nothing("INC-4821.md")])

        line = "    extract failed on handover-note.md: " + EMPTY
        assert line in result.stderr.splitlines(), result.stderr

    def test_a_page_that_failed_is_named(self, workspace: Path, monkeypatch):
        """Row 3 — the one where page 2 of three answered prose twice."""
        pytest.importorskip("pypdfium2", reason="INC-4830 is a PDF: needs dossier[pdf]")
        pytest.importorskip("PIL.Image", reason="the picture converters need Pillow")
        page = _nothing(POSTMORTEM)

        result, model = _run(
            workspace,
            monkeypatch,
            {POSTMORTEM: None},
            [page, NOT_JSON, NOT_JSON, page],
            inputs={"extract": "documents@page_images"},
            modes={"extract": "per_part"},
            convert="    convert:\n      application/pdf: [markdown, page_images]\n",
        )

        assert model.call_count == 4
        line = f"    extract failed on {POSTMORTEM}: page-002.png: {INVALID}"
        assert line in result.stderr.splitlines(), result.stderr

    def test_a_finding_is_not_a_failure(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one with a quote the document does not hold."""
        answer = json.dumps(
            {
                "document": "INC-4821.md",
                "fields": [
                    {
                        "field": "loss_amount",
                        "value": 99999.0,
                        "currency": "CHF",
                        "source": {"document": "INC-4821.md", "span": "CHF 99'999"},
                    }
                ],
            }
        )

        result, _ = _run(workspace, monkeypatch, {"INC-4821.md": TEXT["INC-4821.md"]}, [answer])

        assert result.exit_code == 0, result.output
        assert "1 finding(s)" in result.output, result.output
        assert "failed on" not in result.output + result.stderr
