"""R8.14 — `docling-markdown` OCRs a page only when it has no text layer.

What is proved here is row 4, the reason the converter exists: a photocopied
postmortem, in a workspace that names `docling-markdown`, gives a stage text its
root cause can be grounded in -- on the page it is printed on. Before it, the same
document converted to three anchors and nothing else, and no field in it could
ever be `grounded`.

Run through the CLI because the claim needs every link in the chain: the
workspace's choice of converter (R8.13), Docling reading a page with no text
layer, the anchors it writes, and grounding putting a quoted span on a page
(R6.4, R6.14). Each of them alone proves nothing a person auditing a scanned
contract would notice.

Docling runs for real, so this is `live`: it needs `dossier[docling]` and the
model weights R8.15 names, and it takes about a minute. The model is a fake,
answering with a span from the published PDF's text layer -- the words on the
page, not what OCR made of them -- and citing a page that does not exist, so the
page in the artifact can only have come from grounding.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline
from tests.scans import photocopy

pytestmark = [pytest.mark.outer_loop, pytest.mark.live]

PIPELINE = "incident-audit"

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "postmortems" / "pdf"
PUBLISHED = "INC-4830-postmortem-checkout-tls-expiry.pdf"
PHOTOCOPY = "INC-4830-postmortem-photocopied.pdf"

# Spec 008 R8.14 row 1: the root cause, on page 2 of three.
ROOT_CAUSE = "Certificate renewal and certificate deployment were two separate processes"
ITS_PAGE = 2
# A page the document does not have, so it cannot be copied through by accident.
CLAIMED_PAGE = 8


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _use(monkeypatch, client) -> None:
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


def _answer() -> str:
    return json.dumps(
        {
            "document": PHOTOCOPY,
            "fields": [
                {
                    "field": "root_cause",
                    "value": "the renewed certificate was issued but never deployed",
                    "source": {"document": PHOTOCOPY, "span": ROOT_CAUSE, "page": CLAIMED_PAGE},
                }
            ],
        }
    )


def _workspace(workspace: Path, *, converters: str) -> Path:
    """One photocopied postmortem, from a silent folder source."""
    inbox = workspace / "inbox" / "scans"
    inbox.mkdir(parents=True)
    (inbox / PHOTOCOPY).write_bytes(photocopy((CORPUS / PUBLISHED).read_bytes()))

    (workspace / "sources.yaml").write_text(
        converters + "sources:\n  - id: scans\n    type: folder\n    path: inbox/scans/\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, steps=["extract"], sources=["scans"])
    return workspace


def _cited_page(workspace: Path, monkeypatch) -> int | None:
    """Sync, convert and run the workspace; the page its root cause is cited on."""
    from tests.fakes import FakeModelClient

    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    converted = _cli(workspace, monkeypatch, "convert", PIPELINE)
    assert converted.exit_code == 0, converted.output

    model = FakeModelClient(responses=[_answer()])
    _use(monkeypatch, model)
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    assert model.call_count == 1

    written = next((workspace / "runs").rglob(f"extract/{PHOTOCOPY}.json"))
    return json.loads(written.read_text(encoding="utf-8"))["fields"][0]["source"]["page"]


class TestAPhotocopiedPostmortemIsGrounded:
    """R8.14 — `docling-markdown` OCRs a page only when it has no text layer."""

    def test_a_photocopied_root_cause_is_grounded_on_its_page(
        self, workspace: Path, monkeypatch
    ):
        """Row 4: the one where a scan's root cause is found on page 2.

        The span is the published text layer's, word for word. Grounding finds
        it only if OCR read page 2 of the photocopy back exactly enough, and the
        page follows only if Docling wrote each page behind its anchor.
        """
        pytest.importorskip("docling", reason="needs dossier[docling]")

        scanned = _workspace(workspace, converters="converters: [docling-markdown]\n\n")

        assert _cited_page(scanned, monkeypatch) == ITS_PAGE

    def test_without_docling_the_photocopy_has_nothing_to_ground_in(
        self, workspace: Path, monkeypatch
    ):
        """Counter-example, row 4's other half: the one where nothing names Docling.

        `pdf-markdown` still answers the pair (R8.13 row 1), reads the
        photocopy's empty text layer, and leaves the same quoted root cause with
        no page to be found on. This is what the slice changes, stated as the
        state it changes from.
        """
        pytest.importorskip("pypdfium2", reason="needs dossier[pdf]")

        scanned = _workspace(workspace, converters="")

        assert _cited_page(scanned, monkeypatch) is None
