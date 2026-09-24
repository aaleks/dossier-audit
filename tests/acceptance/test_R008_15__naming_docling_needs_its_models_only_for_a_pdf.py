"""R8.15 — `docling-markdown`'s models are needed by a PDF it converts, not by its name.

Row 5, the counter-example. A workspace can name `docling-markdown` before it
holds a single PDF -- set up for the scans it expects -- and must not fail for
weights nothing is about to read. Through the CLI, in the default suite, with no
weights anywhere and Docling not necessarily installed: the three fixture
documents are markdown, so `markdown-text` answers them and the converter named
for PDFs is never asked.
"""

from __future__ import annotations

from pathlib import Path

PIPELINE = "incident-audit"


def _run(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


class TestNamingDoclingNeedsItsModelsOnlyForAPdf:
    """R8.15 — nothing is checked until a PDF is converted with it."""

    def test_a_workspace_of_markdown_naming_docling_converts_as_before(
        self, workspace: Path, monkeypatch
    ):
        """Row 5: the one where the workspace names Docling and holds no PDF.

        The name is resolved -- a misspelt one would stop the command (R8.13
        row 4) -- and nothing else happens to it: the check stands in front of
        a PDF, and there is none.
        """
        sources = workspace / "sources.yaml"
        sources.write_text(
            "converters: [docling-markdown]\n\n" + sources.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        assert _run(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _run(workspace, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "3 converted" in result.output, result.output
