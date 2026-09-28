"""R7.35 — `--compare` refuses two runs shown different reference documents, by
key or by snapshot.

Through the CLI, because the refusal is only as good as what the command hands
the check: the manifests of both runs, with the reference documents each one
pinned. One incident is audited against two procedures, each kept in a folder
source. Run `a`, then change something, then run `b`, then compare. The model is
a fake that abstains on every field (R0.1). What it answers is not this rule's
business, only whether the two runs may be compared at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

PIPELINE = "incident-audit"
TICKETS = {"INC-4821.md": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n"}
PROCEDURES = {
    "OPS-114.md": "# OPS-114 Incident escalation procedure\n\nEscalate within 30 minutes.\n",
    "OPS-115.md": "# OPS-115 Customer communication\n\nNotify customers within 4 hours.\n",
}
FOLDERS = """\
sources:
  - id: incidents
    type: folder
    path: inbox/tickets/
  - id: procedures
    type: folder
    path: inbox/procedures/
"""
GOLD = {
    "document": "INC-4821.md",
    "verified_by": "a.aleks",
    "verified_at": "2026-09-15",
    "fields": {"loss_amount": {"value": 48200.00, "currency": "CHF"}},
}


class Abstains:
    """Answers every call about the document its `<source_document>` held, abstaining."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        held = re.search(r'<source_document><document key="([^"]+)">', prompt)
        document = held.group(1) if held else ""
        return json.dumps({"document": document, "fields": [abstains(f) for f in FIELDS]})


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _run(workspace: Path, monkeypatch) -> str:
    """Sync and run; the run's id."""
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return re.search(r"^run (\S+)", result.output, re.MULTILINE).group(1)


def _edit_prompt(workspace: Path) -> None:
    """A prompt change, the kind of configuration change `--compare` exists for."""
    prompt = workspace / "pipelines" / PIPELINE / "prompts" / "extract.md"
    prompt.write_text(
        "Read carefully.\n" + prompt.read_text(encoding="utf-8"), encoding="utf-8"
    )


def _compare(workspace: Path, monkeypatch, a: str, b: str):
    return _cli(
        workspace, monkeypatch, "eval", PIPELINE, "--gold", "gold/tickets", "--compare", a, b
    )


@pytest.fixture
def run_a(workspace: Path, monkeypatch) -> str:
    """One incident, `extract` reading it and both procedures; run `a`'s id."""
    import dossier.cli.bootstrap as cli

    for folder, files in (("tickets", TICKETS), ("procedures", PROCEDURES)):
        for name, text in files.items():
            path = workspace / "inbox" / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    gold = workspace / "gold" / "tickets" / "INC-4821.json"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text(json.dumps(GOLD, indent=2) + "\n", encoding="utf-8")
    (workspace / "sources.yaml").write_text(FOLDERS, encoding="utf-8")
    write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["incidents"],
        reference=["procedures"],
        steps=["extract"],
        inputs={"extract": "[documents, reference]"},
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Abstains())
    return _run(workspace, monkeypatch)


class TestCompareRefusesRunsShownDifferentReference:
    """R7.35 — a delta is the configuration's only if the context held still."""

    def test_a_procedure_tightened_between_the_runs_is_refused(
        self, workspace: Path, monkeypatch, run_a: str
    ):
        """Row 1: the one where `OPS-114` was tightened in place before run `b`."""
        (workspace / "inbox" / "procedures" / "OPS-114.md").write_text(
            "# OPS-114 Incident escalation procedure\n\nEscalate within 15 minutes.\n",
            encoding="utf-8",
        )
        _edit_prompt(workspace)
        run_b = _run(workspace, monkeypatch)

        result = _compare(workspace, monkeypatch, run_a, run_b)

        assert result.exit_code == 2, result.output
        assert (
            f"runs {run_a} and {run_b} were shown different reference documents -- "
            "OPS-114.md changed. A field can move because its context did."
        ) in result.output

    def test_the_same_procedures_compare(self, workspace: Path, monkeypatch, run_a: str):
        """Row 3: counter-example -- the one where only the prompt was edited."""
        _edit_prompt(workspace)
        run_b = _run(workspace, monkeypatch)

        result = _compare(workspace, monkeypatch, run_a, run_b)

        assert result.exit_code == 0, result.output
        assert re.search(r"^\s*loss_amount\b", result.output, re.MULTILINE), result.output
