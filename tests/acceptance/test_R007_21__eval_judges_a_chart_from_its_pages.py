"""R7.21 — `dossier eval` scores a chart by putting its pages to the judge.

The end of the road the visual slice started on. `INC-5720` is a chart with no
text layer: it converts to `page_images` and to nothing else, a `per_part` step
reads it one page at a time, the value it answers is `described` because no
string search can confirm it (R6.15), and the judge that decides it is shown the
page rather than a transcript.

Through the CLI because every layer has to agree, and because the defect this
closes was an exception at the top of one: `dossier eval` indexed the converted
text by document key and a picture-only document is not in it.

The judge is a `FakeModelClient`, and it **counts calls** -- two of the rows
here are claims about what it was shown rather than about what it answered.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

from dossier.application.eval import CALIBRATIONS_DIR, SHOWN_AS_PAGES, judge_prompt_hash
from dossier.domain.grounding import DESCRIBED, GROUNDED, judge_name
from dossier.domain.hashing import text_hash

PIPELINE = "incident-audit"
GOLD = "gold/incidents"
JUDGED = "root_cause"
MODEL = "anthropic:claude-sonnet-4-5-20250929"

IMAGES = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "images"
CHART = "INC-5720-checkout-latency-postmortem.png"

pytest.importorskip("PIL.Image", reason="the picture converters need Pillow")

# `_fixtures.md`, "Fields on INC-5720". The span is drawn on the chart and
# written in no sentence, so it is locatable in no text at all.
SPAN = "Total abandoned checkout value over the window:  CHF 132'400"
CAUSE = (
    "Applications opened unbounded connections to the payments-api pool during "
    "the ledger-batch failover, and the retry policy amplified every timeout "
    "into three more."
)

EXTRACTED = json.dumps(
    {
        "document": CHART,
        "fields": [
            {
                "field": JUDGED,
                "value": CAUSE,
                "source": {"document": CHART, "span": SPAN, "page": 1},
            }
        ],
    }
)

VERDICT = json.dumps({"supported": True, "evidence": "the Root cause section says so"})


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _use(monkeypatch, client) -> None:
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


def _calibrate(gold: Path, rubric: Path, *, state: str, agreement: float) -> None:
    """A calibration, as `dossier calibrate` writes one (R7.14, R7.22)."""
    path = gold / CALIBRATIONS_DIR / f"{judge_name(JUDGED, state)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "judge_model": MODEL,
                "rubric_hash": text_hash(rubric),
                "prompt_hash": judge_prompt_hash(),
                "agreement": agreement,
                "sample_size": 22,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def scored_chart(workspace: Path, monkeypatch) -> Path:
    """A completed run over the chart, with a gold answer and both bars agreed."""
    from tests.fakes import FakeModelClient

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
    path = write_pipeline(
        workspace,
        steps=["extract"],
        inputs={"extract": "documents@page_images"},
        outputs={"extract": "schemas/incident.yaml"},
        sources=["charts"],
        modes={"extract": "per_part"},
    )
    path.write_text(path.read_text(encoding="utf-8") + f"gold: {GOLD}/\n", encoding="utf-8")

    gold = workspace / GOLD
    gold.mkdir(parents=True, exist_ok=True)
    (gold / "INC-5720.json").write_text(
        json.dumps(
            {
                "document": CHART,
                "verified_by": "a.aleks",
                "verified_at": "2026-09-19",
                "fields": {
                    JUDGED: {
                        "value": CAUSE,
                        "verified_by": "a.aleks",
                        "verified_at": "2026-09-19",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (gold / "judge.yaml").write_text(
        f"{JUDGED}:\n  {GROUNDED}: 0.95\n  {DESCRIBED}: 0.90\n", encoding="utf-8"
    )
    rubric = path.parent / "rubrics" / "root_cause.md"
    _calibrate(gold, rubric, state=GROUNDED, agreement=1.0)
    _calibrate(gold, rubric, state=DESCRIBED, agreement=0.955)

    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0
    _use(monkeypatch, FakeModelClient(responses=[EXTRACTED]))
    assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
    return workspace


class TestEvalJudgesAChartFromItsPages:
    """R7.21 — the judge is shown the page, and the field is scored."""

    def test_the_judge_is_shown_the_page(self, scored_chart: Path, monkeypatch):
        """Example 1: the one the whole visual slice is evaluated through.

        One call, carrying the page, with a body saying the pages are what it
        has. Before this the command raised `KeyError` here, because a
        picture-only document is absent from the converted-text map.
        """
        from tests.fakes import FakeModelClient

        judge = FakeModelClient(responses=[VERDICT])
        _use(monkeypatch, judge)

        result = _cli(scored_chart, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert judge.call_count == 1
        assert len(judge.calls[0]["parts"]) == 1, "the judge was not shown the page"
        assert SHOWN_AS_PAGES in str(judge.calls[0]["prompt"])

    def test_the_field_is_reported(self, scored_chart: Path, monkeypatch):
        """Example 1, continued: a described verdict counts (R7.23).

        Both states are calibrated and above their bars, so nothing is
        withheld and the field carries a percentage a reader can check against
        `judge.yaml`.
        """
        from tests.fakes import FakeModelClient

        _use(monkeypatch, FakeModelClient(responses=[VERDICT]))

        result = _cli(scored_chart, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert JUDGED in result.output
        assert "100.0%" in result.output, result.output

    def test_a_second_eval_asks_the_judge_nothing(self, scored_chart: Path, monkeypatch):
        """Example 3: the verdict is cached under the pages (R7.18).

        Zero calls is the assertion. A judge is a model, and R0.10 says a model
        is reached only on a cache miss -- which a verdict keyed on evidence
        nobody hashed would quietly stop being true of.
        """
        from tests.fakes import FakeModelClient

        _use(monkeypatch, FakeModelClient(responses=[VERDICT]))
        assert _cli(scored_chart, monkeypatch, "eval", PIPELINE, "--gold", GOLD).exit_code == 0

        second = FakeModelClient(responses=[])
        _use(monkeypatch, second)
        again = _cli(scored_chart, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert again.exit_code == 0, again.output
        assert second.call_count == 0

    def test_an_unmeasured_vision_judge_withholds_the_field(
        self, scored_chart: Path, monkeypatch
    ):
        """R7.23 example 2, end to end: the gate closes on the real command.

        The described calibration is removed and the grounded one left in
        place. The field is withheld whole, and the judge is never asked --
        nothing is measured for a number nobody may print (R7.17).
        """
        from tests.fakes import FakeModelClient

        (scored_chart / GOLD / CALIBRATIONS_DIR / f"{JUDGED}.{DESCRIBED}.json").unlink()
        judge = FakeModelClient(responses=[])
        _use(monkeypatch, judge)

        result = _cli(scored_chart, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert judge.call_count == 0
        assert DESCRIBED in result.output, result.output
        assert "100.0%" not in result.output
