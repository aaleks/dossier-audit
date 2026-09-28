"""R7.51 — `dossier eval` scores a `per_part` step's fields once per document.

What a person auditing postmortems page by page sees: each field counted over
documents, and the page that got one wrong named under it (R7.25). The values
are `_fixtures.md`'s "`INC-4830` page by page", beside `INC-5720`'s one page.

`INC-4830` prints `SEV-1` in the header of all three pages, so a step reading
one page at a time answers `severity` three times; page 1 alone states the
resolution date, and page 2's timeline ends on the day the review was held.
Scored once per page, the three-page document outvoted the one-page picture,
and page 2's date was a third of `resolution_date` rather than half of it.

The model is a `FakeModelClient` answering four pages in order -- the three of
`INC-4830`, then `INC-5720`'s one -- and it **counts calls**: scoring asks
none (R7.10).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

pytestmark = pytest.mark.outer_loop

pytest.importorskip("pypdfium2", reason="INC-4830 is a PDF: needs dossier[pdf]")
pytest.importorskip("PIL.Image", reason="the picture converters need Pillow")

PIPELINE = "incident-audit"
SOURCE = "postmortems"
GOLD = "gold/incidents"
URI = "http://localhost:5000"
FIELDS = ("severity", "resolution_date")

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
CHART = "INC-5720-checkout-latency-postmortem.png"

DECLARATION = """\
fields:
  severity:        {kind: enum, values: [minor, major, critical]}
  resolution_date: {kind: date}
"""

# `_fixtures.md`, "`INC-4830` page by page" and "Fields on INC-5720".
GOLD_ANSWERS = {
    POSTMORTEM: {"severity": "critical", "resolution_date": "2026-07-28"},
    CHART: {"severity": "major", "resolution_date": "2026-09-02"},
}


def _record(document: str, field: str, value: str, span: str) -> dict:
    return {"field": field, "value": value, "source": {"document": document, "span": span}}


def _answer(document: str, *records: dict) -> str:
    return json.dumps({"document": document, "fields": list(records)})


# One reply per page, in the order the run asks: documents in key order, each
# one's pages in part order. The spans on `INC-4830` are in its text layer, so
# every value there is grounded and a miss is about the value, not the evidence.
PAGES = [
    _answer(
        POSTMORTEM,
        _record(POSTMORTEM, "severity", "critical", "SEV-1"),
        _record(POSTMORTEM, "resolution_date", "2026-07-28", "2026-07-28"),
    ),
    _answer(
        POSTMORTEM,
        _record(POSTMORTEM, "severity", "critical", "SEV-1"),
        _record(POSTMORTEM, "resolution_date", "2026-07-30", "2026-07-30"),
    ),
    _answer(POSTMORTEM, _record(POSTMORTEM, "severity", "critical", "SEV-1")),
    _answer(
        CHART,
        _record(CHART, "severity", "major", "status: closed"),
        _record(CHART, "resolution_date", "2026-09-02", "2026-09-02"),
    ),
]


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _line_of(output: str, field: str) -> str:
    return next((line for line in output.splitlines() if line.split()[:1] == [field]), "")


def _lines_under(output: str, field: str) -> list[str]:
    """The indented lines following `field`'s own line, up to the next field."""
    lines = output.splitlines()
    starts = [i for i, line in enumerate(lines) if line.split()[:1] == [field]]
    if not starts:
        return []
    collected = []
    for line in lines[starts[0] + 1 :]:
        if line.split()[:1] and line.split()[0] in FIELDS:
            break
        collected.append(line)
    return [line for line in collected if line.strip()]


def _write_gold(workspace: Path, answers: dict[str, dict[str, str]]) -> None:
    gold = workspace / GOLD
    gold.mkdir(parents=True, exist_ok=True)
    for document, fields in answers.items():
        (gold / f"{document[:8]}.json").write_text(
            json.dumps(
                {
                    "document": document,
                    "verified_by": "a.aleks",
                    "verified_at": "2026-09-28",
                    "fields": {field: {"value": value} for field, value in fields.items()},
                }
            ),
            encoding="utf-8",
        )


def _audited(workspace: Path, monkeypatch, gold: dict[str, dict[str, str]]):
    """The postmortem and the chart synced, converted and run page by page."""
    from tests.fakes import FakeModelClient

    import dossier.cli.bootstrap as cli

    inbox = workspace / "inbox" / "postmortems"
    inbox.mkdir(parents=True)
    shutil.copy(FIXTURES / "postmortems" / "pdf" / POSTMORTEM, inbox / POSTMORTEM)
    shutil.copy(FIXTURES / "images" / CHART, inbox / CHART)

    # The PDF is read as pages and searched as text; the picture converts to
    # its default, `page_images`, and has no text to search (R8.10, R8.26).
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: folder\n    path: inbox/postmortems/\n"
        "    convert:\n      application/pdf: [markdown, page_images]\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        steps=["extract"],
        inputs={"extract": "documents@page_images"},
        outputs={"extract": "schemas/incident.yaml"},
        sources=[SOURCE],
        modes={"extract": "per_part"},
        write_declaration=False,
    )
    (workspace / "pipelines" / PIPELINE / "schemas" / "incident.yaml").write_text(
        DECLARATION, encoding="utf-8"
    )
    _write_gold(workspace, gold)

    model = FakeModelClient(responses=list(PAGES))
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)
    for args in (("sync", PIPELINE), ("convert", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    return model


def _eval(workspace: Path, monkeypatch):
    from tests.fakes import NoModelClient

    import dossier.cli.bootstrap as cli

    # Every field here is scored without a judge (R7.10): a call would be a finding.
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


class TestEvalScoresAPerPartFieldOncePerDocument:
    """R7.51 — `dossier eval` scores a `per_part` step's fields once per document."""

    def test_each_field_is_counted_over_documents_not_pages(self, workspace: Path, monkeypatch):
        """Row 1 — the one where a three-page postmortem weighs what a one-page chart does.

        Two documents, so two verdicts a field: `severity` right on both, and
        `resolution_date` wrong on `INC-4830` because page 2 gave another date.
        Four model calls, one a page, all of them made by `run`.
        """
        model = _audited(workspace, monkeypatch, GOLD_ANSWERS)

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert "2 documents · 2 fields · overall 75.0%" in result.output, result.output
        assert "100.0%" in _line_of(result.output, "severity"), result.output
        assert "50.0%" in _line_of(result.output, "resolution_date"), result.output
        assert model.call_count == 4

    def test_the_page_that_got_it_wrong_is_named(self, workspace: Path, monkeypatch):
        """Row 2 — the one where the miss says which page gave the other date."""
        _audited(workspace, monkeypatch, GOLD_ANSWERS)

        result = _eval(workspace, monkeypatch)

        under = _lines_under(result.output, "resolution_date")
        named = next((line for line in under if "INC-4830" in line), "")
        assert "page-002.png: '2026-07-30' does not match '2026-07-28'" in named, result.output
        assert _lines_under(result.output, "severity") == [], result.output

    def test_mlflow_records_the_figures_the_terminal_printed(
        self, workspace: Path, monkeypatch
    ):
        """Row 3 — the one where MLflow holds the per-document figures, not the per-page ones.

        Tracking is switched on after the run, so the eval's is the only run
        the fake holds (R11.3).
        """
        from tests.fakes import FakeTracker

        import dossier.cli.bootstrap as cli

        _audited(workspace, monkeypatch, GOLD_ANSWERS)
        recorder = FakeTracker()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert len(recorder.runs) == 1, "one eval is one MLflow run"
        metrics = recorder.runs[0].metrics
        assert metrics["accuracy/severity"] == 100.0
        assert metrics["accuracy/resolution_date"] == 50.0
        assert metrics["accuracy/overall"] == 75.0

    def test_a_field_gold_did_not_verify_names_no_page(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one where nobody verified INC-4830's date.

        `resolution_date` is scored on `INC-5720` alone, and page 2's date is
        not named: there is no verified answer for it to disagree with
        (R7.3 row 4).
        """
        _audited(
            workspace,
            monkeypatch,
            {**GOLD_ANSWERS, POSTMORTEM: {"severity": "critical"}},
        )

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert "100.0%" in _line_of(result.output, "resolution_date"), result.output
        assert "page-002.png" not in result.output, result.output
