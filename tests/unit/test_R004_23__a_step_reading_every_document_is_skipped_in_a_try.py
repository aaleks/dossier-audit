"""R4.23 — under `--doc`, a step that reads every document is skipped, and the
try says so.

An `aggregate` step's input is every document. Asked about the named ones, it
would answer a question about a subset, cached under a key no full run uses,
and easily read as the real report. So it is not asked, and its step line says
why.

Through the CLI, because the line is read there. The incidents are markdown in
a folder source, so their keys carry the extension (`INC-4821.md`), as R3.17's
do. The model is a fake that keeps every prompt, so the calls are **counted**.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

PIPELINE = "incident-audit"
INCIDENTS = {
    "INC-4821.md": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822.md": "# INC-4822\n\nThe payment gateway timed out for two hours.\n",
}
SHOWN = re.compile(r'<document key="([^"]+)">')
SKIPPED = "  report: skipped under --doc: it reads every document"


class Model:
    """Answers every call, and keeps each prompt: `extract` a record, `report` prose."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.prompts.append(prompt)
        shown = SHOWN.findall(prompt)
        if schema is None:
            return "Two incidents, both closed."
        return json.dumps({"document": shown[0], "fields": [abstains(f) for f in FIELDS]})


def _dossier_run(workspace: Path, monkeypatch, *documents: str) -> tuple[Model, object]:
    """`extract` per_file, then `report` aggregate, with `--doc` for each of `documents`."""
    import dossier.cli.bootstrap as cli

    for name, text in INCIDENTS.items():
        path = workspace / "inbox" / "tickets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        "sources:\n  - id: tickets\n    type: folder\n    path: inbox/tickets/\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["tickets"],
        steps=["extract", "report"],
        modes={"report": "aggregate"},
        outputs={"report": None},
    )
    model = Model()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    named = [argument for document in documents for argument in ("--doc", document)]
    return model, _cli(workspace, monkeypatch, "run", PIPELINE, *named)


class TestAStepReadingEveryDocumentIsSkippedInATry:
    """R4.23 — under `--doc`, an `aggregate` step is skipped, and the try says so."""

    def test_the_report_is_not_asked_about_one_incident(self, workspace: Path, monkeypatch):
        """Row 1 — the one where the try asks `extract` about INC-4821 and nothing else."""
        model, result = _dossier_run(workspace, monkeypatch, "INC-4821.md")

        assert result.exit_code == 0, result.output
        assert [SHOWN.findall(prompt) for prompt in model.prompts] == [["INC-4821.md"]]
        assert SKIPPED in result.output.splitlines(), result.output

    def test_a_run_asks_the_report_once_over_every_incident(self, workspace: Path, monkeypatch):
        """Row 2, counter-example — the one with no `--doc`: the report, as always."""
        model, result = _dossier_run(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert [SHOWN.findall(prompt) for prompt in model.prompts] == [
            ["INC-4821.md"],
            ["INC-4822.md"],
            ["INC-4821.md", "INC-4822.md"],
        ]
        assert "  report: 1 document(s) · 0 from cache · 0 failed" in result.output, (
            result.output
        )
