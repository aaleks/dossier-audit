"""R3.12 — a `per_part` step calls the model once per part of its input.

The slice the whole visual-evidence conversation was for. A PDF is rendered to
one picture per page (R8.11), a `describe` step is shown one page at a time, and
what it writes is text a later step can read -- and a person can check against
the page it came from.

Run through the CLI because every layer has to agree for it to be true: the
converter produced a container, the pipeline named the kind (R3.11), the step
fanned out over the parts, each call was handed its own picture (R9.16), and
each answer landed under its own name (R0.13).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "postmortems" / "pdf"
PDF = "INC-4830-postmortem-checkout-tls-expiry.pdf"
PAGES = 3

pytest.importorskip("pypdfium2", reason="the describe slice needs the 'pdf' extra")


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _use(monkeypatch, client) -> None:
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


@pytest.fixture
def describes_pages(workspace: Path) -> Path:
    """A workspace whose one source is rendered to page images and described."""
    inbox = workspace / "inbox" / "postmortems"
    inbox.mkdir(parents=True)
    shutil.copy(CORPUS / PDF, inbox / PDF)

    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: postmortems\n"
        "    type: folder\n"
        "    path: inbox/postmortems/\n"
        "    convert: [markdown, page_images]\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        steps=["describe"],
        inputs={"describe": "documents@page_images"},
        outputs={"describe": None},
        sources=["postmortems"],
        modes={"describe": "per_part"},
    )
    return workspace


class TestADescribeStepReadsOnePageAtATime:
    """R3.12 — one call per page, one artifact per page."""

    def test_each_page_is_its_own_call_and_its_own_artifact(
        self, describes_pages: Path, monkeypatch
    ):
        """Example 1: the one the visual-evidence slice exists for.

        Three calls for a three-page document, each shown one picture, each
        written under its own name (R0.13). The call count is the assertion
        that matters: a step that sent all three pages to one call would
        produce one artifact and look almost right.
        """
        from tests.fakes import FakeModelClient

        model = FakeModelClient(responses=[f"page {n} shows a chart." for n in (1, 2, 3)])

        assert _cli(describes_pages, monkeypatch, "sync", PIPELINE).exit_code == 0
        assert _cli(describes_pages, monkeypatch, "convert", PIPELINE).exit_code == 0
        _use(monkeypatch, model)

        result = _cli(describes_pages, monkeypatch, "run", PIPELINE)
        assert result.exit_code == 0, result.output

        assert model.call_count == PAGES
        assert all(len(call["parts"]) == 1 for call in model.calls), (
            "each call is shown one page, not the whole document"
        )

        written = sorted((describes_pages / "runs").rglob(f"describe/{PDF}/page-*.md"))
        assert [path.name for path in written] == [
            "page-001.md",
            "page-002.md",
            "page-003.md",
        ]

    def test_a_second_run_asks_the_model_nothing(self, describes_pages: Path, monkeypatch):
        """Example 4: the one where every part is cached on its own (R5.5).

        Per-part keys are worth having only if they hit per part. Zero calls is
        the assertion; a step that re-described one page would still exit zero.
        """
        from tests.fakes import FakeModelClient

        _cli(describes_pages, monkeypatch, "sync", PIPELINE)
        _cli(describes_pages, monkeypatch, "convert", PIPELINE)
        _use(monkeypatch, FakeModelClient(responses=[f"page {n}." for n in (1, 2, 3)]))
        assert _cli(describes_pages, monkeypatch, "run", PIPELINE).exit_code == 0

        second = FakeModelClient(responses=[])
        _use(monkeypatch, second)
        again = _cli(describes_pages, monkeypatch, "run", PIPELINE)

        assert again.exit_code == 0, again.output
        assert second.call_count == 0
