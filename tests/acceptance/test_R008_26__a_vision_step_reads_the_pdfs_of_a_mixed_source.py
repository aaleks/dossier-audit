"""R8.26 — `convert:` may map a media type to its kinds, and a document whose
media type the map does not name gets its default.

Row 2, from the command line. A folder holds a scanned PDF and a markdown note,
and a step reads the scan's pages as pictures. The list form cannot say that:
`convert: [markdown, page_images]` asks `page_images` of the note too, nothing
claims `(text/markdown, page_images)`, and the run stops before anything
converts (R8.24). A Confluence space exporting PDFs had the same problem with
every page's JSON (R1.19).

The map asks `page_images` of the PDF alone. The note converts to its default,
`markdown`, and the step is not asked about it: it holds nothing the step reads
(R6.21).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
SOURCE = "incidents-mixed"

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SCAN = "PLAY-2001-terminal-scan.pdf"
NOTE = "INC-4821.md"

pytest.importorskip("pypdfium2", reason="the scan is a PDF: needs dossier[pdf]")


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _mixed(workspace: Path, convert: str) -> Path:
    """A folder holding a scan and a note, and a step reading pages as pictures."""
    inbox = workspace / "inbox" / "mixed"
    inbox.mkdir(parents=True)
    shutil.copy(FIXTURES / "documents" / "scans" / SCAN, inbox / SCAN)
    shutil.copy(FIXTURES / "inbox" / "incidents" / NOTE, inbox / NOTE)

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: folder\n    path: inbox/mixed/\n{convert}",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        steps=["extract"],
        inputs={"extract": "documents@page_images"},
        outputs={"extract": "schemas/incident.yaml"},
        sources=[SOURCE],
        modes={"extract": "per_part"},
    )
    return workspace


class TestAVisionStepReadsThePdfsOfAMixedSource:
    """R8.26 row 2 — the map says which documents a kind is for."""

    def test_the_scan_is_read_as_pictures_and_the_note_as_text(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where the note is not asked for pictures it cannot have.

        Three artifacts: the scan's text and its page, and the note's text. Then
        one model call, for the scan's one page. The note is converted, and no
        step reads markdown, so nothing asks about it.
        """
        from tests.fakes import FakeModelClient

        import dossier.cli.bootstrap as cli

        mixed = _mixed(
            workspace,
            "    convert:\n      application/pdf: [markdown, page_images]\n",
        )
        assert _cli(mixed, monkeypatch, "sync", PIPELINE).exit_code == 0

        converted = _cli(mixed, monkeypatch, "convert", PIPELINE)

        assert converted.exit_code == 0, converted.output
        assert "2 held · 3 converted · 0 cached" in converted.output

        model = FakeModelClient(responses=[json.dumps({"document": SCAN, "fields": []})])
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)

        result = _cli(mixed, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert model.call_count == 1, "one page of one scan, and nothing for the note"
        assert len(model.calls[0]["parts"]) == 1, "the page reached the model as a picture"

    def test_the_list_form_still_asks_every_document(self, workspace: Path, monkeypatch):
        """Counter-example (row 5): the one where the list asks the note for pictures.

        `convert: [markdown, page_images]` is unchanged: both kinds of every
        document, and `(text/markdown, page_images)` is a pair nothing claims,
        so the run stops before anything converts (R8.24).
        """
        mixed = _mixed(workspace, "    convert: [markdown, page_images]\n")
        assert _cli(mixed, monkeypatch, "sync", PIPELINE).exit_code == 0

        converted = _cli(mixed, monkeypatch, "convert", PIPELINE)

        assert converted.exit_code == 2, converted.output
        assert "('text/markdown', 'page_images')" in converted.output
