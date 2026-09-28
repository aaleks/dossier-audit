"""R6.15 — a field read off a picture is `described`, counted apart from grounded.

A source that declares `convert: [page_images]` and nothing else produces no
text at all. R6.4 locates a span by searching converted text, so its answer for
every field such a stage produces is `ungrounded` -- "the value may be right,
and nothing in the document shows it", about a document that shows it plainly,
on a page the model looked at.

Run through the CLI because the claim spans every layer: the converter made
pictures and no markdown, the step named the kind, the stage was handed the
page, and grounding was told which documents it had been shown that way rather
than inferring it from a text map that happens to be empty.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "postmortems" / "pdf"
PDF = "INC-4830-postmortem-checkout-tls-expiry.pdf"
PAGES = 3

pytest.importorskip("pypdfium2", reason="the described slice needs the 'pdf' extra")

# A span quoted off the rendered page. It appears in no converted text, because
# this source was never converted to text -- which is the whole rule.
SPAN = "total exposure CHF 48'200"

DESCRIBED = json.dumps(
    {
        "document": PDF,
        "fields": [
            {
                "field": "loss_amount",
                "value": 48200.00,
                "currency": "CHF",
                "source": {"document": PDF, "span": SPAN, "page": 1},
            }
        ],
    }
)

# The other two pages have nothing to say about the field, and say so (R6.5).
ABSTAINED = json.dumps(
    {
        "document": PDF,
        "fields": [
            {
                "field": "loss_amount",
                "value": None,
                "reason": "this page shows the timeline, not the exposure",
            }
        ],
    }
)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _use(monkeypatch, client) -> None:
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


@pytest.fixture
def reads_pictures(workspace: Path) -> Path:
    """A workspace whose one source is rendered to pages and to no text at all."""
    inbox = workspace / "inbox" / "postmortems"
    inbox.mkdir(parents=True)
    shutil.copy(CORPUS / PDF, inbox / PDF)

    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: postmortems\n"
        "    type: folder\n"
        "    path: inbox/postmortems/\n"
        "    convert: [page_images]\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        steps=["extract"],
        inputs={"extract": "documents@page_images"},
        outputs={"extract": "schemas/incident.yaml"},
        sources=["postmortems"],
        modes={"extract": "per_part"},
    )
    return workspace


def _responses() -> list[str]:
    """Page 1 answers; pages 2 and 3 abstain."""
    return [DESCRIBED] + [ABSTAINED] * (PAGES - 1)


class TestARunCountsDescribedFieldsApartFromGrounded:
    """R6.15 — the third grounding state, end to end."""

    def test_a_value_read_off_a_page_is_described_not_ungrounded(
        self, reads_pictures: Path, monkeypatch
    ):
        """Example 1: the one the visual-evidence slice exists for.

        Asserting on the summary line rather than on an internal verdict is
        deliberate. An `ungrounded` field is scored incorrect before any
        comparison (R7.4), so getting this wrong stays invisible until a figure
        in a report is wrong, which is far too late to notice it.

        The two abstaining pages are example 5: a picture does not turn a null
        into a claim, so they are counted as neither described nor failed.
        """
        from tests.fakes import FakeModelClient

        assert _cli(reads_pictures, monkeypatch, "sync", PIPELINE).exit_code == 0
        assert _cli(reads_pictures, monkeypatch, "convert", PIPELINE).exit_code == 0
        _use(monkeypatch, FakeModelClient(responses=_responses()))

        result = _cli(reads_pictures, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "0 failed · 1 described" in result.output, result.output

    def test_the_described_field_is_written_with_its_value_intact(
        self, reads_pictures: Path, monkeypatch
    ):
        """Example 4: described is not a failure, so nothing is discarded.

        A described field treated as a failure would leave no artifact at all
        (R0.11) while the run still exited zero -- the shape of bug that turns
        up three reports later as a gap nobody can date.
        """
        from tests.fakes import FakeModelClient

        _cli(reads_pictures, monkeypatch, "sync", PIPELINE)
        _cli(reads_pictures, monkeypatch, "convert", PIPELINE)
        _use(monkeypatch, FakeModelClient(responses=_responses()))
        assert _cli(reads_pictures, monkeypatch, "run", PIPELINE).exit_code == 0

        written = sorted((reads_pictures / "runs").rglob(f"extract/{PDF}/page-001.json"))
        assert len(written) == 1, [str(path) for path in written]

        fields = json.loads(written[0].read_text(encoding="utf-8"))["fields"]
        assert fields[0]["value"] == 48200.00
