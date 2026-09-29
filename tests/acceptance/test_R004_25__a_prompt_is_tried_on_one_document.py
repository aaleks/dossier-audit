"""R4.25 — a prompt is tried on one document, again and again, and the
pipeline's result stays the last full run's.

The slice's acceptance rule. R4.18 to R4.24 can each be MET while the loop a
person iterates in is broken, so this runs it as they do: a full run, a prompt
edited, `dossier run --doc` on the document that shows the problem, the prompt
edited again, tried again, and `dossier eval` still reporting the full run.

The documents are `_fixtures.md`'s `INC-4830`, three pages read page by page,
and `INC-5720`, one page. The model is a `FakeModelClient` answering pages in
the order they are asked, and it **counts calls**: a try asks only about the
named document (R4.18), and scoring asks none (R7.10).
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

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
CHART = "INC-5720-checkout-latency-postmortem.png"
PAGES = ["page-001.json", "page-002.json", "page-003.json"]

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


def _postmortem(first_date: str) -> list[str]:
    """`INC-4830`'s three pages, in part order. Every span is in its text layer."""
    return [
        _answer(
            POSTMORTEM,
            _record(POSTMORTEM, "severity", "critical", "SEV-1"),
            _record(POSTMORTEM, "resolution_date", first_date, first_date),
        ),
        _answer(POSTMORTEM, _record(POSTMORTEM, "severity", "critical", "SEV-1")),
        _answer(POSTMORTEM, _record(POSTMORTEM, "severity", "critical", "SEV-1")),
    ]


# The full run answers every field as gold does. Each try answers the date
# differently, so a try scored as the pipeline's result would show on `eval`.
FULL_RUN = [
    *_postmortem("2026-07-28"),
    _answer(
        CHART,
        _record(CHART, "severity", "major", "status: closed"),
        _record(CHART, "resolution_date", "2026-09-02", "2026-09-02"),
    ),
]
FIRST_TRY = _postmortem("2026-07-26")
SECOND_TRY = _postmortem("2026-07-27")

# What the person adds to the prompt before each try.
EDITS = ("The resolution date is the day the fix was confirmed.", "Not the day of the review.")


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _write_gold(workspace: Path) -> None:
    gold = workspace / GOLD
    gold.mkdir(parents=True, exist_ok=True)
    for document, fields in GOLD_ANSWERS.items():
        (gold / f"{document[:8]}.json").write_text(
            json.dumps(
                {
                    "document": document,
                    "verified_by": "a.aleks",
                    "verified_at": "2026-09-29",
                    "fields": {field: {"value": value} for field, value in fields.items()},
                }
            ),
            encoding="utf-8",
        )


def _audited(workspace: Path, monkeypatch):
    """The postmortem and the chart synced, converted and run page by page, in full."""
    from tests.fakes import FakeModelClient

    import dossier.cli.bootstrap as cli

    inbox = workspace / "inbox" / "postmortems"
    inbox.mkdir(parents=True)
    shutil.copy(FIXTURES / "postmortems" / "pdf" / POSTMORTEM, inbox / POSTMORTEM)
    shutil.copy(FIXTURES / "images" / CHART, inbox / CHART)
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
    _write_gold(workspace)

    model = FakeModelClient(responses=[*FULL_RUN, *FIRST_TRY, *SECOND_TRY])
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)
    for args in (("sync", PIPELINE), ("convert", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    assert model.call_count == 4, "the full run asks once a page: three and one"
    return model


def _edit_prompt(workspace: Path, line: str) -> None:
    prompt = workspace / "pipelines" / PIPELINE / "prompts" / "extract.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + f"\n{line}\n", encoding="utf-8")


def _try(workspace: Path, monkeypatch, *documents: str):
    arguments = [argument for document in documents for argument in ("--doc", document)]
    return _cli(workspace, monkeypatch, "run", PIPELINE, *arguments)


def _directories(path: Path) -> list[str]:
    if not path.is_dir():
        return []
    return sorted(entry.name for entry in path.iterdir() if entry.is_dir())


def _eval(workspace: Path, monkeypatch):
    from tests.fakes import NoModelClient

    import dossier.cli.bootstrap as cli

    # Neither field is judged (R7.10): a model call here would be a finding.
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


class TestAPromptIsTriedOnOneDocument:
    """R4.25 — a prompt is tried on one document, again and again, and the
    pipeline's result stays the last full run's."""

    def test_a_try_asks_about_the_one_document_and_writes_under_tries(
        self, workspace: Path, monkeypatch
    ):
        """Row 1 — the one where the edited prompt is tried on the postmortem alone."""
        model = _audited(workspace, monkeypatch)
        runs = _directories(workspace / "runs")
        _edit_prompt(workspace, EDITS[0])

        result = _try(workspace, monkeypatch, POSTMORTEM)

        assert result.exit_code == 0, result.output
        assert model.call_count == 4 + 3, "three pages of INC-4830, and nothing of INC-5720"
        tries = _directories(workspace / "tries")
        assert len(tries) == 1, tries
        (try_id,) = tries
        assert result.output.splitlines()[0] == f"try {try_id} · tries/{try_id}/", result.output
        answers = workspace / "tries" / try_id / "extract" / POSTMORTEM
        assert all((answers / page).is_file() for page in PAGES), sorted(answers.glob("*"))
        assert _directories(workspace / "runs") == runs, "a try is not a run (R4.20)"

    def test_the_prompt_is_edited_again_and_tried_again(self, workspace: Path, monkeypatch):
        """Row 2 — the one where the second try is asked afresh and kept apart."""
        model = _audited(workspace, monkeypatch)
        runs = _directories(workspace / "runs")
        _edit_prompt(workspace, EDITS[0])
        first = _try(workspace, monkeypatch, POSTMORTEM)
        assert first.exit_code == 0, first.output
        _edit_prompt(workspace, EDITS[1])

        second = _try(workspace, monkeypatch, POSTMORTEM)

        assert second.exit_code == 0, second.output
        assert model.call_count == 4 + 3 + 3, "the prompt is in the key: asked again"
        assert len(_directories(workspace / "tries")) == 2
        assert _directories(workspace / "runs") == runs

    def test_eval_still_reports_the_full_run(self, workspace: Path, monkeypatch):
        """Row 3 — the one where two tries later, the pipeline's result is unchanged.

        The full run answered as gold does; each try gave `INC-4830` another
        resolution date. Scored as the result, either would show as 75.0%.
        """
        _audited(workspace, monkeypatch)
        for line in EDITS:
            _edit_prompt(workspace, line)
            assert _try(workspace, monkeypatch, POSTMORTEM).exit_code == 0

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert "2 documents · 2 fields · overall 100.0%" in result.output, result.output

    def test_a_document_no_source_holds_is_asked_nothing(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one where the key is mistyped."""
        model = _audited(workspace, monkeypatch)

        result = _try(workspace, monkeypatch, "INC-4899")

        assert result.exit_code == 2, result.output
        assert "INC-4899" in result.output, result.output
        assert model.call_count == 4, "a mistyped key asks nothing"
        assert _directories(workspace / "tries") == []
