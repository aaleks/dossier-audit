"""R3.18 — `{{reference}}` holds every reference document, each under its own key
in key order, whatever the step's mode.

`reference:` is context: an escalation procedure every incident is verified
against. So every call reading it is shown all of it, and the call for one
incident is shown exactly what the call for the next is. Run through the CLI
because every layer has to agree for it to be true: the pipeline names the
reference sources, the run reads them apart from the audited ones, and each
call's prompt is rendered with them.

The documents are markdown in two folder sources, so a folder's keys carry the
extension, `OPS-114.md`, as `audit-note.pdf` does in `_fixtures.md`. The
incidents are kept in `inbox/tickets/`, because the workspace fixture already
fills `inbox/incidents/`. The rule is
about which documents a placeholder holds, not their format. The model is a
fake that records every prompt it is sent (R0.1).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
INCIDENTS = {
    "INC-4821.md": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822.md": "# INC-4822\n\nThe payment gateway timed out for two hours.\n",
}
PROCEDURES = {
    "OPS-114.md": "# OPS-114 Incident escalation procedure\n\nEscalate within 30 minutes.\n",
    "OPS-115.md": "# OPS-115 Customer communication\n\nNotify customers within 4 hours.\n",
    "OPS-116.md": "# OPS-116 Post-incident review\n\nHold a review within 5 days.\n",
}
SOURCES = """\
sources:
  - id: incidents
    type: folder
    path: inbox/tickets/
  - id: procedures
    type: folder
    path: inbox/procedures/
"""
SHOWN = re.compile(r'<document key="([^"]+)">')


def _section(prompt: str, tag: str) -> str | None:
    """What one labelled input of a prompt holds, or None if it has no such input."""
    match = re.search(rf"<{tag}>(.*?)</{tag}>", prompt, re.DOTALL)
    return None if match is None else match.group(1)


class Model:
    """Answers every call, and remembers every prompt it was sent.

    A structured answer abstains on every field, and names the document its
    `<source_document>` held. Which documents each call was shown is this rule's
    business; what was extracted is not.
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.prompts.append(prompt)
        if schema is None:
            return "Two incidents, both escalated late."
        audited = SHOWN.findall(_section(prompt, "source_document") or "")
        return json.dumps({"document": audited[0], "fields": [abstains(f) for f in FIELDS]})

    def calls_about(self, key: str, *, reading: str) -> list[str]:
        """The prompts of the calls about `key` that hold a `<reading>` input."""
        return [
            prompt
            for prompt in self.prompts
            if _section(prompt, reading) is not None
            and SHOWN.findall(_section(prompt, "source_document") or "") == [key]
        ]


def _workspace(
    workspace: Path,
    monkeypatch,
    *,
    steps: list[str],
    inputs: dict[str, str],
    modes: dict[str, str] | None = None,
    outputs: dict[str, str | None] | None = None,
    reference: list[str] | None = ["procedures"],  # noqa: B006 -- read, never mutated
) -> Model:
    """Two incidents to audit, three procedures as reference, and the model served."""
    import dossier.cli.main as cli

    for folder, files in (("tickets", INCIDENTS), ("procedures", PROCEDURES)):
        for name, text in files.items():
            path = workspace / "inbox" / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    (workspace / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["incidents"],
        reference=reference,
        steps=steps,
        inputs=inputs,
        modes=modes,
        outputs=outputs,
    )
    model = Model()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return model


VERIFYING = "[documents, extract, reference]"
VERIFY = {"steps": ["extract", "verify"], "inputs": {"verify": VERIFYING}}


class TestEveryCallIsShownEveryReferenceDocument:
    """R3.18 — context is the same for every document it is context for."""

    def test_a_per_file_call_holds_every_reference_document_in_key_order(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where the incident is verified against the procedures.

        `{{reference}}` holds the three procedures, each under its own key and
        with its own text, and not the incident a second time.
        """
        model = _workspace(workspace, monkeypatch, **VERIFY)
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        (prompt,) = model.calls_about("INC-4821.md", reading="procedure")
        held = _section(prompt, "procedure")
        assert SHOWN.findall(held) == ["OPS-114.md", "OPS-115.md", "OPS-116.md"]
        assert "Escalate within 30 minutes." in held

    def test_every_call_is_shown_the_same_reference(self, workspace: Path, monkeypatch):
        """Row 2: the one where the next incident is verified against the same context."""
        model = _workspace(workspace, monkeypatch, **VERIFY)
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        (first,) = model.calls_about("INC-4821.md", reading="procedure")
        (second,) = model.calls_about("INC-4822.md", reading="procedure")
        assert SHOWN.findall(_section(second, "procedure")) == [
            "OPS-114.md",
            "OPS-115.md",
            "OPS-116.md",
        ]
        assert _section(first, "procedure") == _section(second, "procedure")

    def test_an_aggregate_call_holds_the_reference_once(self, workspace: Path, monkeypatch):
        """Row 3: the one where a report reads the verified answers and the context.

        One call, and the three procedures in it once, each under its own key.
        """
        model = _workspace(
            workspace,
            monkeypatch,
            steps=["extract", "verify", "report"],
            inputs={"verify": VERIFYING, "report": "[verify, reference]"},
            modes={"report": "aggregate"},
            outputs={"report": None},
        )
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        (report,) = [p for p in model.prompts if _section(p, "verify") is not None]
        assert SHOWN.findall(_section(report, "procedure")) == [
            "OPS-114.md",
            "OPS-115.md",
            "OPS-116.md",
        ]

    def test_reading_reference_that_no_source_supplies_is_refused(
        self, workspace: Path, monkeypatch
    ):
        """Row 4: the one where the pipeline declares no `reference:` at all.

        `verify` would be shown nothing and told it was the context. Refused at
        load, naming the step, and no model is asked anything.
        """
        model = _workspace(workspace, monkeypatch, **VERIFY, reference=None)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "'verify'" in result.output
        assert "reference" in result.output
        assert model.prompts == []

    def test_a_step_that_does_not_read_reference_is_shown_none(
        self, workspace: Path, monkeypatch
    ):
        """Row 5, a counter-example: the one where the step reads `documents` only.

        `extract` is asked about each incident, and no procedure is anywhere in
        its prompt.
        """
        model = _workspace(workspace, monkeypatch, **VERIFY)
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        extracting = [
            prompt
            for key in INCIDENTS
            for prompt in model.calls_about(key, reading="source_document")
            if _section(prompt, "procedure") is None
        ]
        assert len(extracting) == 2
        assert all("OPS-11" not in prompt for prompt in extracting)
