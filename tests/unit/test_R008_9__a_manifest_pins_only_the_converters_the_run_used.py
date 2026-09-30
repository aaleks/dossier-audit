"""R8.9 — a manifest pins the converters the run used, and only those.

"Used" is decided the way selection is (R8.3): a converter is used when it
claims the `(media type, kind)` pair of some document the run holds, under that
document's source's `convert:` list. The decision is `domain.conversion.used`,
tested directly; rows 1 and 2 go through the CLI as well, because the place the
decision was missing was the composition root, which pinned whatever
`installed_converters()` returned.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

import dossier.infrastructure.converters.registry as registry
from dossier.domain.conversion import Converter

PIPELINE = "incident-audit"
DOCUMENTS = ("INC-4821.md", "INC-4822.md", "audit-note.md")

MARKDOWN_TEXT = Converter(
    id="markdown-text", version="1.0.0", media_type="text/markdown", kind="markdown"
)
PDF_MARKDOWN = Converter(
    id="pdf-markdown", version="1.3.0", media_type="application/pdf", kind="markdown"
)
PDF_MARKDOWN_RAISED = PDF_MARKDOWN.model_copy(update={"version": "1.4.0"})
PDF_IMAGES = Converter(
    id="pdf-images", version="0.9.1", media_type="application/pdf", kind="page_images"
)


class MarkdownText:
    id = "markdown-text"
    version = "1.0.0"
    media_type = "text/markdown"
    kind = "markdown"

    def convert(self, payload: bytes, options) -> bytes:
        return payload


class PdfMarkdown:
    id = "pdf-markdown"
    version = "1.3.0"
    media_type = "application/pdf"
    kind = "markdown"

    def convert(self, payload: bytes, options) -> bytes:
        return b"# " + payload


class _StubEntryPoint:
    def __init__(self, converter: type) -> None:
        self.name = converter.id
        self.group = registry.ENTRY_POINT_GROUP
        self._converter = converter

    def load(self) -> type:
        return self._converter


def installed(monkeypatch, *converters: type) -> None:
    """What `dossier.converters` entry points this machine carries."""
    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda group: (
            [_StubEntryPoint(c) for c in converters]
            if group == registry.ENTRY_POINT_GROUP
            else []
        ),
    )


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _answer(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "summary",
                    "value": "reviewed",
                    "source": {"document": document, "span": "Reopened"},
                }
            ],
        }
    )


@pytest.fixture
def ran(workspace: Path, monkeypatch) -> Path:
    """A run over the markdown-only folder source, with a PDF converter installed too."""
    from tests.fakes import FakeModelClient

    import dossier.cli.bootstrap as cli

    installed(monkeypatch, MarkdownText, PdfMarkdown)
    write_pipeline(workspace, steps=["extract"])
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    client = FakeModelClient(responses=[_answer(key) for key in DOCUMENTS])
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    (run,) = (workspace / "runs").iterdir()
    return run


class TestAManifestPinsOnlyTheConvertersTheRunUsed:
    """R8.9 — pinned because a held document needed it, never because it was installed."""

    def test_a_converter_nothing_held_needed_is_not_pinned(self):
        """Example 1: the one where a PDF converter is installed and no PDF is held."""
        from dossier.domain.conversion import used

        pinned = used(
            requests=[("text/markdown", None)] * 3,
            available=[PDF_MARKDOWN, MARKDOWN_TEXT],
        )

        assert pinned == [MARKDOWN_TEXT]

    def test_the_manifest_of_a_markdown_run_names_markdown_text_alone(self, ran: Path):
        """Example 1, through the CLI: the one where the composition root decides."""
        manifest = json.loads((ran / "manifest.json").read_text(encoding="utf-8"))

        assert [(c["id"], c["version"]) for c in manifest["plan"]["converters"]] == [
            ("markdown-text", "1.0.0")
        ]

    def test_uninstalling_an_unused_converter_changes_no_plan(
        self, workspace: Path, monkeypatch, ran: Path
    ):
        """Example 2: the one where the PDF plugin is removed and `--plan` says `cached`.

        Nothing the run read moved, so nothing would miss (R4.12). Before this
        rule the plan printed `converters changed` here, a promise to re-ask that
        the run would not have kept.
        """
        from tests.fakes import NoModelClient

        import dossier.cli.bootstrap as cli

        installed(monkeypatch, MarkdownText)
        monkeypatch.setattr(
            cli, "build_model_client", lambda model_id: NoModelClient(), raising=False
        )

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert "extract: cached" in result.output, result.output
        assert "converters changed" not in result.output, result.output

    def test_a_converter_a_held_document_needs_is_pinned(self):
        """Example 3: the one where `OPS-114` is a PDF beside the markdown.

        In a stable order, so two machines write the same bytes (R4.8).
        """
        from dossier.domain.conversion import used

        pinned = used(
            requests=[("text/markdown", None), ("application/pdf", ["markdown"])],
            available=[PDF_IMAGES, PDF_MARKDOWN, MARKDOWN_TEXT],
        )

        assert pinned == [MARKDOWN_TEXT, PDF_MARKDOWN]

    def test_a_used_converter_is_pinned_at_the_version_installed(self):
        """Counter-example (row 4): the one where `pdf-markdown` was raised and is still used.

        What is pinned follows the installed version, which is what lets R4.12
        row 6 report `converters changed` for a converter that *was* used.
        """
        from dossier.domain.conversion import used

        pinned = used(
            requests=[("application/pdf", ["markdown"])],
            available=[PDF_MARKDOWN_RAISED, MARKDOWN_TEXT],
        )

        assert pinned == [PDF_MARKDOWN_RAISED]

    def test_a_document_nothing_claims_pins_nothing_and_stops_nothing(self):
        """Example 3 beside R8.25: the one where a file nothing converts is held first.

        It fails on its own and pins no converter; the markdown after it is
        still pinned.
        """
        from dossier.domain.conversion import used

        pinned = used(
            requests=[("application/x-ndjson", None), ("text/markdown", None)],
            available=[PDF_MARKDOWN, MARKDOWN_TEXT],
        )

        assert pinned == [MARKDOWN_TEXT]

    def test_a_run_holding_nothing_pins_nothing(self):
        """Counter-example (row 5): the one over an empty source (R4.12 row 10)."""
        from dossier.domain.conversion import used

        assert used(requests=[], available=[PDF_MARKDOWN, MARKDOWN_TEXT]) == []
