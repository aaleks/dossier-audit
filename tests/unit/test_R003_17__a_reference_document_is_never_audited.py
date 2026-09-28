"""R3.17 — a `reference` document is context and is never audited: no step is
asked about it, and nothing is filed under its key.

`reference:` names the procedures incidents are verified against. A procedure
has no loss amount, so a call asking it for one answers a question nobody
asked, is paid for, and is scored against no gold. The audited documents are
those of `sources:`, and every mode fans out over them alone.

Through the CLI, because which documents are audited is decided where `dossier
run` reads its sources. The documents are markdown in folder sources, so their
keys carry the extension (`OPS-114.md`), and the incidents are kept in
`inbox/tickets/` because the workspace fixture already fills
`inbox/incidents/`. The model is a fake that records every prompt (R0.1).
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
PROCEDURES = {"OPS-114.md": "# OPS-114 Incident escalation\n\nEscalate in 30 minutes.\n"}
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """Answers every call with nothing extracted, and remembers each prompt."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.prompts.append(prompt)
        audited = SHOWN.findall(prompt)
        return json.dumps({"document": audited[0], "fields": [abstains(f) for f in FIELDS]})


def _run(
    workspace: Path, monkeypatch, *, mode: str = "per_file", audited: tuple[str, ...] = ()
) -> tuple[Model, object]:
    """Sync and run one `extract` step over two incidents, with one procedure as reference.

    `audited` names sources listed under `sources:` beside `tickets`.
    """
    import dossier.cli.bootstrap as cli

    for folder, files in (("tickets", INCIDENTS), ("procedures", PROCEDURES)):
        for name, text in files.items():
            path = workspace / "inbox" / folder / name
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
        sources=["tickets", *audited],
        reference=["procedures"],
        modes={"extract": mode},
    )
    model = Model()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return model, result


def _filed(workspace: Path) -> list[str]:
    (run,) = [path for path in (workspace / "runs").iterdir() if path.is_dir()]
    filed = (run / "extract").iterdir()
    return sorted(path.name for path in filed if not path.name.endswith(".meta.json"))


class TestAReferenceDocumentIsNeverAudited:
    """R3.17 — context is read, never asked about."""

    def test_a_per_file_step_is_asked_about_the_incidents_alone(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where two incidents are audited and a procedure is not."""
        model, result = _run(workspace, monkeypatch)

        assert len(model.prompts) == 2
        assert _filed(workspace) == ["INC-4821.md.json", "INC-4822.md.json"]
        assert "extract: 2 document(s)" in result.output

    def test_an_aggregate_step_is_shown_the_incidents_alone(self, workspace: Path, monkeypatch):
        """Row 2: the one where one call reads every audited document."""
        model, _ = _run(workspace, monkeypatch, mode="aggregate")

        (prompt,) = model.prompts
        assert SHOWN.findall(prompt) == ["INC-4821.md", "INC-4822.md"]

    def test_a_procedure_is_in_no_group(self, workspace: Path, monkeypatch):
        """Row 3: the one where the step asks once per group."""
        model, _ = _run(workspace, monkeypatch, mode="per_group")

        assert sorted(SHOWN.findall(prompt)[0] for prompt in model.prompts) == [
            "INC-4821.md",
            "INC-4822.md",
        ]

    def test_a_source_listed_both_ways_is_audited_too(self, workspace: Path, monkeypatch):
        """Row 4, a counter-example: the one where `procedures` is under `sources:` as well.

        Listed both ways, it is read both ways: its procedure is audited like
        an incident.
        """
        model, _ = _run(workspace, monkeypatch, audited=("procedures",))

        assert len(model.prompts) == 3
        assert "OPS-114.md.json" in _filed(workspace)
