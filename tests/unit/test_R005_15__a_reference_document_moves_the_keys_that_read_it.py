"""R5.15 — a step that reads `reference` holds every reference document's text in
each of its keys, and a step that does not holds none.

Context moves every answer given with it. `verify` is shown every procedure in
each call (R3.18), so editing one asks it again about every incident; `extract`
never read a procedure, so the edit costs it nothing. Counted in model calls,
per step, because that is what a key moving costs (R5.5).

Through the CLI: a run, a change synced, and a second run. Folder sources, so
keys carry the extension; the incidents are kept in `inbox/tickets/` because
the workspace fixture fills `inbox/incidents/`.
"""

from __future__ import annotations

import json
import re
from collections import Counter
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
    "OPS-115.md": "# OPS-115 Customer communication\n\nNotify within 4 hours.\n",
    "OPS-116.md": "# OPS-116 Post-incident review\n\nHold a review within 5 days.\n",
}
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """Answers every call with nothing extracted, and counts calls per step.

    A call is `verify`'s when its prompt holds a `<procedure>` input.
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.shown: list[list[str]] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        step = "verify" if "<procedure>" in prompt else "extract"
        self.calls[step] += 1
        audited = SHOWN.findall(prompt)
        if step == "verify":
            self.shown.append(SHOWN.findall(prompt.split("<procedure>", 1)[1]))
        return json.dumps({"document": audited[0], "fields": [abstains(f) for f in FIELDS]})


def _ran_twice(workspace: Path, monkeypatch, change) -> Model:
    """Run, apply `change` to the inbox, sync, and run again; the second run's model."""
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
    first = Model()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: first)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
    assert first.calls == {"extract": 2, "verify": 2}

    change(inbox)
    second = Model()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: second)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output
    return second


def _edit(inbox: Path, relative: str, text: str) -> None:
    (inbox / relative).write_text(text, encoding="utf-8")


class TestAReferenceDocumentMovesTheKeysThatReadIt:
    """R5.15 — context is in the keys of the steps shown it, and of no other."""

    def test_an_edited_procedure_asks_the_reading_step_again(
        self, workspace: Path, monkeypatch
    ):
        """Rows 1 and 2: the one where `OPS-114` moves on.

        `verify` is asked again about both incidents; `extract` about neither.
        """
        model = _ran_twice(
            workspace,
            monkeypatch,
            lambda inbox: _edit(
                inbox,
                "procedures/OPS-114.md",
                "# OPS-114 Incident escalation\n\nEscalate within 15 minutes.\n",
            ),
        )

        assert model.calls == {"verify": 2}

    def test_a_tombstoned_procedure_asks_the_reading_step_again(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where `OPS-116` is gone, and two procedures are left."""
        model = _ran_twice(
            workspace, monkeypatch, lambda inbox: (inbox / "procedures" / "OPS-116.md").unlink()
        )

        assert model.calls == {"verify": 2}
        assert model.shown == [["OPS-114.md", "OPS-115.md"]] * 2

    def test_an_edited_incident_asks_about_that_incident_alone(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, a counter-example: the one where an incident moves, not the context.

        R5.10 unchanged: one incident, one call per step, and `INC-4822`'s keys
        stay where they were.
        """
        model = _ran_twice(
            workspace,
            monkeypatch,
            lambda inbox: _edit(
                inbox,
                "tickets/INC-4821.md",
                "# INC-4821\n\nFinance confirmed a total exposure CHF 48'900.\n",
            ),
        )

        assert model.calls == {"extract": 1, "verify": 1}
