"""R8.12 — an image source syncs, converts and runs end to end.

The pair `(image/png, page_images)` was the one R8.10 resolved to and nothing
produced, so every image source stopped the run at R8.5. A screenshot could be
synced, held and hashed, and never converted.

`INC-5720` is the document that makes this matter rather than merely work: it is
a chart with no text layer, stating a figure no sentence anywhere contains. It
is unreadable by every stage dossier had before pictures, and the two visual
judge cases in `root_cause_visual.jsonl` are about it.

`convert: [page_images]` is declared, because R4.13 row 1 refuses a step that
reads a kind an undeclared source was never told to make. R8.10's default kind
table governs `dossier convert` and is proved by its own acceptance test; what
this one proves is that the pair it resolves to is now a pair something makes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"

IMAGES = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "images"
CHART = "INC-5720-checkout-latency-postmortem.png"

pytest.importorskip("PIL.Image", reason="the picture converters need Pillow")

# Quoted off the chart, where it is drawn and nowhere written.
SPAN = "Total abandoned checkout value over the window:  CHF 132'400"

ANSWER = json.dumps(
    {
        "document": CHART,
        "fields": [
            {
                "field": "loss_amount",
                "value": 132400.00,
                "currency": "CHF",
                "source": {"document": CHART, "span": SPAN, "page": 1},
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
def chart_source(workspace: Path) -> Path:
    """A workspace whose one source is a picture, rendered to its one page."""
    inbox = workspace / "inbox" / "charts"
    inbox.mkdir(parents=True)
    shutil.copy(IMAGES / CHART, inbox / CHART)

    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: charts\n"
        "    type: folder\n"
        "    path: inbox/charts/\n"
        "    convert: [page_images]\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        steps=["extract"],
        inputs={"extract": "documents@page_images"},
        outputs={"extract": "schemas/incident.yaml"},
        sources=["charts"],
        modes={"extract": "per_part"},
    )
    return workspace


class TestAnImageSourceRunsEndToEnd:
    """R8.12 — the pair R8.10 resolves to is one something produces."""

    def test_a_chart_is_converted_and_read(self, chart_source: Path, monkeypatch):
        """Example 1: the one where a picture becomes evidence.

        Three commands, because the failure this fixes was at the second one:
        conversion stopped the whole run naming a pair nothing claimed, and no
        amount of work in `run` could reach past it.
        """
        from tests.fakes import FakeModelClient

        model = FakeModelClient(responses=[ANSWER])

        assert _cli(chart_source, monkeypatch, "sync", PIPELINE).exit_code == 0
        assert _cli(chart_source, monkeypatch, "convert", PIPELINE).exit_code == 0
        _use(monkeypatch, model)

        result = _cli(chart_source, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert model.call_count == 1, "one page, one call"
        assert len(model.calls[0]["parts"]) == 1, "the page reached the model as a picture"

    def test_the_figure_drawn_on_the_chart_is_described(self, chart_source: Path, monkeypatch):
        """Example 1, continued: what the run leaves behind (R6.15).

        The span is drawn on the chart and written in no sentence, so it is not
        locatable in any text -- `described`, and counted as such. That is the
        whole point of the document and the reason it is in the gold sample.
        """
        from tests.fakes import FakeModelClient

        _cli(chart_source, monkeypatch, "sync", PIPELINE)
        _cli(chart_source, monkeypatch, "convert", PIPELINE)
        _use(monkeypatch, FakeModelClient(responses=[ANSWER]))

        result = _cli(chart_source, monkeypatch, "run", PIPELINE)

        assert "0 failed · 1 described" in result.output, result.output

        written = next((chart_source / "runs").rglob(f"extract/{CHART}/page-001.json"))
        assert (
            json.loads(written.read_text(encoding="utf-8"))["fields"][0]["value"] == 132400.00
        )
