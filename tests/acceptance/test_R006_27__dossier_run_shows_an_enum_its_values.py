"""R6.27 — `dossier run` shows a model an enum field's values, and names an
answer outside them.

The slice's acceptance rule. R6.25 (the schema) and R6.26 (the finding) are
each provable alone, and either could be MET while the slice is broken, as
R3.16 was: proved where the pipeline loaded while every reader was handed
nothing. So this runs the CLI, from the declaration to the schema a model is
handed and the line `run` prints, and reads the finding back through `eval`.

`_fixtures.md`'s "`INC-4830` page by page": every page prints `SEV-1`, and
gold's `critical` is a reviewer's reading of it. A model not shown the
vocabulary quotes the document and is wrong about the field.

The model is a `FakeModelClient` answering the three pages in order, and it
**counts calls**: scoring asks none (R7.10).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

pytest.importorskip("pypdfium2", reason="INC-4830 is a PDF: needs dossier[pdf]")
pytest.importorskip("PIL.Image", reason="the picture converters need Pillow")

PIPELINE = "incident-audit"
SOURCE = "postmortems"
GOLD = "gold/incidents"
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
VOCABULARY = {"minor", "major", "critical", None}
FINDING = "severity: 'SEV-1' is not one of minor, major, critical"

DECLARATION = """\
fields:
  severity:        {kind: enum, values: [minor, major, critical]}
  resolution_date: {kind: date}
"""


def _record(field: str, value: str, span: str) -> dict:
    return {"field": field, "value": value, "source": {"document": POSTMORTEM, "span": span}}


def _page(*records: dict) -> str:
    return json.dumps({"document": POSTMORTEM, "fields": list(records)})


def _pages(first_severity: str) -> list[str]:
    """One reply per page, in part order. Every span is in the PDF's text layer."""
    return [
        _page(
            _record("severity", first_severity, "SEV-1"),
            _record("resolution_date", "2026-07-28", "2026-07-28"),
        ),
        _page(_record("severity", "critical", "SEV-1")),
        _page(_record("severity", "critical", "SEV-1")),
    ]


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _run(workspace: Path, monkeypatch, replies: list[str]):
    """The postmortem synced, converted and run page by page; the run's result and model."""
    from tests.fakes import FakeModelClient

    import dossier.cli.bootstrap as cli

    inbox = workspace / "inbox" / "postmortems"
    inbox.mkdir(parents=True)
    shutil.copy(FIXTURES / "postmortems" / "pdf" / POSTMORTEM, inbox / POSTMORTEM)
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
    gold = workspace / GOLD
    gold.mkdir(parents=True, exist_ok=True)
    (gold / "INC-4830.json").write_text(
        json.dumps(
            {
                "document": POSTMORTEM,
                "verified_by": "a.aleks",
                "verified_at": "2026-09-29",
                "fields": {
                    "severity": {"value": "critical"},
                    "resolution_date": {"value": "2026-07-28"},
                },
            }
        ),
        encoding="utf-8",
    )

    model = FakeModelClient(responses=replies)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)
    for args in (("sync", PIPELINE), ("convert", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    return _cli(workspace, monkeypatch, "run", PIPELINE), model


def _eval(workspace: Path, monkeypatch):
    from tests.fakes import NoModelClient

    import dossier.cli.bootstrap as cli

    # Neither field is judged (R7.10): a model call here would be a finding.
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


def _allowed(value: dict) -> set | None:
    """The values a `value` schema admits, or `None` when it admits any."""
    if "const" in value:
        return {value["const"]}
    if "enum" in value:
        return set(value["enum"])
    if value.get("type") == "null":
        return {None}
    if "anyOf" in value:
        branches = [_allowed(branch) for branch in value["anyOf"]]
        return None if None in branches else set().union(*branches)
    return None


def _records_naming(schema: object, field: str) -> list[set | None]:
    """What each record in the schema able to name `field` lets its `value` hold."""
    found: list[set | None] = []
    if isinstance(schema, dict):
        named = schema.get("properties", {}).get("field")
        if isinstance(named, dict):
            names = [named["const"]] if "const" in named else named.get("enum", [])
            if field in names:
                found.append(_allowed(schema["properties"].get("value", {})))
        for inner in schema.values():
            found.extend(_records_naming(inner, field))
    elif isinstance(schema, list):
        for inner in schema:
            found.extend(_records_naming(inner, field))
    return found


def _line_of(output: str, field: str) -> str:
    return next((line for line in output.splitlines() if line.split()[:1] == [field]), "")


class TestDossierRunShowsAnEnumItsValues:
    """R6.27 — a model is shown an enum's values, and an answer outside them is named."""

    def test_every_call_is_shown_the_vocabulary(self, workspace: Path, monkeypatch):
        """Row 1 — the one where the model is told which words `severity` takes."""
        result, model = _run(workspace, monkeypatch, _pages("critical"))

        assert result.exit_code == 0, result.output
        assert model.call_count == 3
        for call in model.calls:
            assert _records_naming(call["schema"], "severity") == [VOCABULARY], (
                "a record able to name `severity` may hold a value outside its vocabulary"
            )

    def test_an_answer_outside_the_vocabulary_is_named(self, workspace: Path, monkeypatch):
        """Row 2 — the one where page 1 quotes the header instead of the vocabulary."""
        result, _ = _run(workspace, monkeypatch, _pages("SEV-1"))

        assert result.exit_code == 0, result.output
        assert "1 finding(s)" in result.output, result.output
        assert f"    {POSTMORTEM}  {FINDING}" in result.output.splitlines(), result.output
        assert "0 failed" in result.output, result.output

    def test_eval_reads_the_same_finding_back(self, workspace: Path, monkeypatch):
        """Row 3 — the one where the finding is re-derived on read, and no model is asked."""
        _run(workspace, monkeypatch, _pages("SEV-1"))

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert "0.0%" in _line_of(result.output, "severity"), result.output
        assert f"page-001.png: {FINDING}" in result.output, result.output
        assert "100.0%" in _line_of(result.output, "resolution_date"), result.output

    def test_only_the_case_differing_is_no_finding(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one where `Critical` is `critical`, case folded."""
        _run(workspace, monkeypatch, _pages("Critical"))

        result = _eval(workspace, monkeypatch)

        assert "finding" not in result.output, result.output
        assert "100.0%" in _line_of(result.output, "severity"), result.output
