"""R8.13 — a pair is answered by the converter `sources.yaml` names for it.

Through the CLI, because that is where the file is read and the decision is
made before anything converts. The decision is proved row by row in the unit
tests beside this; what is proved here is that `dossier convert` makes it at all
-- that `converters:` is not a key the file may hold and nothing reads, which is
what it was until this.

Row 2 itself, Docling answering a PDF, needs Docling and is the outer loop's
(`test_R008_14__a_photocopied_postmortem_is_grounded.py`).
"""

from __future__ import annotations

from pathlib import Path

PIPELINE = "incident-audit"


def _run(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _name_converters(workspace: Path, line: str) -> None:
    sources = workspace / "sources.yaml"
    sources.write_text(line + sources.read_text(encoding="utf-8"), encoding="utf-8")


def _converted(workspace: Path) -> list[Path]:
    return [
        path
        for path in (workspace / ".dossier" / "cache").rglob("*")
        if path.is_file() and not path.name.endswith(".meta.json")
    ]


class TestAWorkspaceNamesTheConverterThatAnswers:
    """R8.13 — `converters:` in `sources.yaml` reaches the command that converts."""

    def test_a_misspelt_name_stops_convert_before_anything_converts(
        self, workspace: Path, monkeypatch
    ):
        """Row 4: the one where `docling-markdown` is misspelt.

        Stopped by name, with nothing converted. Ignored, the workspace would
        convert with `markdown-text` while its author read the file and
        believed it had chosen something.
        """
        assert _run(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        _name_converters(workspace, "converters: [docling-markdwn]\n\n")

        result = _run(workspace, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "docling-markdwn" in result.output, result.output
        assert _converted(workspace) == []

    def test_naming_the_converter_that_answers_anyway_converts_as_before(
        self, workspace: Path, monkeypatch
    ):
        """Counter-example: the one where the workspace names `markdown-text`.

        A name on a pair with one claimant is the answer that pair already had,
        so the three fixture documents convert exactly as they do unnamed.
        """
        assert _run(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        _name_converters(workspace, "converters: [markdown-text]\n\n")

        result = _run(workspace, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "3 converted" in result.output, result.output
