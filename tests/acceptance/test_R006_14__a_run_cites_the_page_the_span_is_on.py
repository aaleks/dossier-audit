"""R6.14 — `source.page` is derived from the located span.

The rule is a domain decision and is proved row by row in
`tests/unit/test_R006_14__the_page_is_derived_from_the_located_span.py`. What is
proved here is the thing an auditor does with it: open the run's artifact, read
the page number, and turn to that page.

Run through the CLI over a real PDF, because the number only becomes trustworthy
once a converter has emitted anchors, a stage has quoted a span, and grounding
has put the two together. Each of those alone proves nothing about the figure a
person navigates by.

The model is a fake answering a span it was handed from the converted text, and
deliberately citing the **wrong** page beside it. That is the whole claim: the
number in the artifact is the one the document supports, not the one the answer
asserted.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "postmortems" / "pdf"
# Three pages, and the phrase below is on the last of them -- so a converter that
# read only the first page, or a derivation that always answered 1, both fail.
PDF = "INC-4830-postmortem-checkout-tls-expiry.pdf"

# What the fake model will claim as its page. Any number that is not the real one
# does; 8 is chosen because the document has three pages, so a page that cannot
# exist is visibly not being copied through.
CLAIMED_PAGE = 8


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _use(monkeypatch, client) -> None:
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


def _converted_pages(pdf: Path) -> list[str]:
    """The converter's own answer, so the span below is one the document has."""
    from dossier.infrastructure.converters.pdf_markdown import PdfMarkdownConverter

    text = PdfMarkdownConverter().convert(pdf.read_bytes(), {}).decode("utf-8")
    from dossier.domain.grounding import split_pages

    return split_pages(text)


@pytest.fixture
def pdf_workspace(workspace: Path) -> Path:
    """A workspace holding one three-page postmortem, from a silent source."""
    inbox = workspace / "inbox" / "postmortems"
    inbox.mkdir(parents=True)
    shutil.copy(CORPUS / PDF, inbox / PDF)

    (workspace / "sources.yaml").write_text(
        "sources:\n  - id: postmortems\n    type: folder\n    path: inbox/postmortems/\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, steps=["extract"], sources=["postmortems"])
    return workspace


@pytest.fixture
def last_page_span(pdf_workspace: Path) -> tuple[str, int]:
    """A phrase from the document's final page, and that page's number.

    Taken from the converted text rather than written by hand: a literal would
    make this a test of whether PDFium's extraction matches a string typed a
    year ago, and the claim here is about the page, not the prose.
    """
    pages = _converted_pages(pdf_workspace / "inbox" / "postmortems" / PDF)
    last = len(pages)
    line = next(
        line.strip() for line in reversed(pages[-1].splitlines()) if len(line.strip()) > 25
    )
    return line, last


@pytest.mark.outer_loop
class TestARunCitesThePageTheSpanIsOn:
    """R6.14 — the page in the artifact is the document's, not the answer's."""

    def test_the_artifact_cites_the_page_the_span_is_actually_on(
        self, pdf_workspace: Path, last_page_span, monkeypatch
    ):
        """The one where the model cites page 8 of a three-page document.

        Both halves matter. The page in the artifact is the real one, which is
        the rule; and it is not `CLAIMED_PAGE`, which is what shows the number
        was derived rather than copied.
        """
        from tests.fakes import FakeModelClient

        span, real_page = last_page_span
        assert real_page != CLAIMED_PAGE, "the fixture must not agree by accident"

        answer = json.dumps(
            {
                "document": PDF,
                "fields": [
                    {
                        "field": "root_cause",
                        "value": "the renewed certificate was never deployed",
                        "source": {
                            "document": PDF,
                            "span": span,
                            "page": CLAIMED_PAGE,
                        },
                    }
                ],
            }
        )

        assert _cli(pdf_workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        assert _cli(pdf_workspace, monkeypatch, "convert", PIPELINE).exit_code == 0
        _use(monkeypatch, FakeModelClient(responses=[answer]))

        result = _cli(pdf_workspace, monkeypatch, "run", PIPELINE)
        assert result.exit_code == 0, result.output

        written = next((pdf_workspace / "runs").rglob(f"extract/{PDF}.json"))
        record = json.loads(written.read_text(encoding="utf-8"))
        page = record["fields"][0]["source"]["page"]

        assert page == real_page
        assert page != CLAIMED_PAGE, "the model's number reached the artifact"
