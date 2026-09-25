"""R8.21 — `html-markdown` converts an HTML file to markdown of what a reader sees.

What is proved here is row 2, the reason it and `text-csv` (R8.23) exist: a
source holding an exported wiki page and an exported register converts whole.
Before them, `dossier convert` stopped on `(text/html, markdown)` and
`(text/csv, markdown)` before converting anything (R8.5), and the documents it
could read were stopped with them. Synced from Apache's Jira, `KAFKA-20416`
carries both kinds of file, and a Jira source is where they usually arrive.

A folder source rather than a Jira one, because the claim is about the pairs,
not about where the files came from. The three files are
`tests/fixtures/documents/`: two exports promoted from the playground corpus
and a scan with a text layer, a document `dossier` could always read.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.outer_loop

PIPELINE = "export-audit"
SOURCE = "incidents-exports"

DOCUMENTS = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
FILES = (
    DOCUMENTS / "exports" / "PLAY-4001-payment-retries.html",
    DOCUMENTS / "exports" / "PLAY-4004-incident-register.csv",
    DOCUMENTS / "scans" / "PLAY-2001-terminal-scan.pdf",
)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def exports_workspace(workspace: Path) -> Path:
    """A workspace whose one source is a folder of exported files and a scan.

    The source declares no `convert:`, so each file gets its media type's
    default kind, `markdown` for all three (R8.10).
    """
    pytest.importorskip("pypdfium2", reason="the scan is a PDF: needs dossier[pdf]")
    inbox = workspace / "inbox" / "exports"
    inbox.mkdir(parents=True)
    for path in FILES:
        shutil.copy(path, inbox / path.name)

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: folder\n    path: inbox/exports/\n",
        encoding="utf-8",
    )
    pipeline = workspace / "pipelines" / PIPELINE
    shutil.copytree(workspace / "pipelines" / "incident-audit", pipeline)
    text = (pipeline / "pipeline.yaml").read_text(encoding="utf-8")
    (pipeline / "pipeline.yaml").write_text(
        text.replace("sources: [incidents-manual]", f"sources: [{SOURCE}]"), encoding="utf-8"
    )
    return workspace


def _notes(workspace: Path) -> list[str]:
    root = workspace / ".dossier" / "cache" / "convert"
    return [
        path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file() and not path.name.endswith(".json")
    ]


class TestExportedFilesNoLongerStopASource:
    """R8.21 row 2 — an exported page and register convert beside a scan."""

    def test_a_folder_of_exports_converts_whole(self, exports_workspace: Path, monkeypatch):
        """Row 2: the one where nothing is stopped by an HTML page or a CSV file."""
        synced = _cli(exports_workspace, monkeypatch, "sync", PIPELINE)
        assert synced.exit_code == 0, synced.output

        converted = _cli(exports_workspace, monkeypatch, "convert", PIPELINE)

        assert converted.exit_code == 0, converted.output
        assert "3 converted" in converted.output, converted.output
        page = [note for note in _notes(exports_workspace) if "PLAY-4001 — Duplicate" in note]
        assert len(page) == 1, "the exported page has one artifact, holding its title"
        # Once, as the page's heading: the `<title>` is in the `<head>`, which a
        # reader never sees, and the breadcrumb above the heading is kept.
        heading = "# PLAY-4001 — Duplicate payment retries after a queue redelivery\n"
        assert heading in page[0]
        assert page[0].count("Duplicate payment retries") == 1
