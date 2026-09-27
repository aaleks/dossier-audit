"""R4.17 — `--plan` re-runs a step for a moved reference document exactly when
the step reads `reference`.

R4.12's promise, for context. A moved procedure moves every key of a step that
was shown it, and no key of a step that was not (R5.15). A procedure that has
gone is a move too: an audited document leaving takes only its own keys with
it, but a reference document was in every call that read `reference`.

Through the CLI, `dossier run` and then `dossier run --plan`, because the plan
has to pin reference documents apart as the run does (R4.16), or it compares
unlike with like. Folder sources, so keys carry the extension; the incidents are
kept in `inbox/tickets/` because the workspace fixture fills `inbox/incidents/`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

PIPELINE = "incident-audit"
TICKETS = {
    "INC-4821.md": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822.md": "# INC-4822\n\nThe payment gateway timed out for two hours.\n",
}
PROCEDURES = {
    "OPS-114.md": "# OPS-114 Incident escalation\n\nEscalate within 30 minutes.\n",
    "OPS-116.md": "# OPS-116 Post-incident review\n\nHold a review within 5 days.\n",
}
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """Answers every call with nothing extracted."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        audited = SHOWN.findall(prompt)
        return json.dumps({"document": audited[0], "fields": [abstains(f) for f in FIELDS]})


def _ran(workspace: Path, monkeypatch) -> Path:
    """Sync and run `extract`, then `verify` reading the procedures; the inbox."""
    import dossier.cli.main as cli

    inbox = workspace / "inbox"
    for folder, files in (("tickets", TICKETS), ("procedures", PROCEDURES)):
        for name, text in files.items():
            path = inbox / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: tickets\n    type: folder\n    path: inbox/tickets/\n"
        "  - id: procedures\n    type: folder\n    path: inbox/procedures/\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["tickets"],
        reference=["procedures"],
        steps=["extract", "verify"],
        inputs={"verify": "[documents, extract, reference]"},
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output
    return inbox


def _planned(workspace: Path, monkeypatch) -> dict[str, list[str]]:
    """Sync, then plan: each step's status line and the lines under it."""
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")
    assert result.exit_code == 0, result.output
    steps: dict[str, list[str]] = {}
    current = ""
    for line in result.output.splitlines():
        if line[:2] in ("! ", "  ") and not line.startswith("    "):
            current = line[2:].split(":", 1)[0]
            steps[current] = [line]
        elif current and line.startswith("      "):
            steps[current].append(line.strip())
    return steps


class TestAMovedReferenceDocumentRerunsTheStepsReadingIt:
    """R4.17 — context moves only the steps that read it."""

    def test_a_moved_procedure_reruns_the_step_that_reads_it(
        self, workspace: Path, monkeypatch
    ):
        """Rows 1 and 2: the one where `OPS-114` is edited.

        `verify` was shown it and re-runs, naming it. `extract` never read it,
        and is cached.
        """
        inbox = _ran(workspace, monkeypatch)
        (inbox / "procedures" / "OPS-114.md").write_text(
            "# OPS-114 Incident escalation\n\nEscalate within 15 minutes.\n", encoding="utf-8"
        )

        steps = _planned(workspace, monkeypatch)

        assert steps["verify"] == ["! verify: documents changed", "moved: [OPS-114.md changed]"]
        assert steps["extract"] == ["  extract: cached"]

    def test_a_procedure_that_has_gone_reruns_the_step_that_read_it(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where `OPS-116` is tombstoned.

        Every `verify` call was shown it, so every one of its keys moves.
        """
        inbox = _ran(workspace, monkeypatch)
        (inbox / "procedures" / "OPS-116.md").unlink()

        steps = _planned(workspace, monkeypatch)

        assert steps["verify"] == ["! verify: documents changed", "moved: [OPS-116.md gone]"]
        assert steps["extract"] == ["  extract: cached"]

    def test_a_moved_incident_names_no_procedure(self, workspace: Path, monkeypatch):
        """Row 4, a counter-example: the one where the incident moves, not the context."""
        inbox = _ran(workspace, monkeypatch)
        (inbox / "tickets" / "INC-4821.md").write_text(
            "# INC-4821\n\nFinance confirmed a total exposure CHF 48'900.\n", encoding="utf-8"
        )

        steps = _planned(workspace, monkeypatch)

        for step in ("extract", "verify"):
            assert steps[step] == [
                f"! {step}: documents changed",
                "moved: [INC-4821.md changed]",
            ]
