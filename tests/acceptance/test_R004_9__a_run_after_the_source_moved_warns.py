"""R4.9 row 4 — a `dossier run` after the source moved resolves against the
current snapshots and says the source has moved since the last run.

The counter-example to replay's frozen pins (rows 1-3): a *new* run reads what
is held now, and the one thing it owes a person is the line saying two runs are
no longer over the same evidence -- before R7.8 refuses to compare them. The
warning is printed before any step runs, so it is read rather than scrolled.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    FIELDS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
    abstains,
)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def source(workspace: Path, monkeypatch) -> IssueTracker:
    """The four incidents, synced and run once; the source can then be changed."""
    import dossier.cli.main as cli

    tracker = IssueTracker(ISSUES)
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: tracker)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    return tracker


class TestARunAfterTheSourceMovedWarns:
    """R4.9 row 4 — a new run reads what is held now, and says so."""

    def test_a_re_snapshotted_document_is_named_before_any_step_runs(
        self, workspace: Path, monkeypatch, source: IssueTracker
    ):
        """The one where `INC-4821` was re-snapshotted between two runs.

        The warning names the run it is measured against and the document that
        moved, and comes before the run's own lines.
        """
        first = sorted(path.name for path in (workspace / "runs").iterdir())[-1]
        source.issues["INC-4821"] = ISSUES["INC-4821"] + "Addendum: reviewed by finance.\n"
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert (
            lines[0]
            == f"warning: the source has moved since run {first}: INC-4821 re-snapshotted"
        )
        assert re.search(r"^run (\S+)", result.output, re.MULTILINE), "the run still happens"

    def test_a_source_exactly_as_the_last_run_read_it_prints_no_warning(
        self, workspace: Path, monkeypatch, source: IssueTracker
    ):
        """The one where nothing moved: no warning, nothing to scroll past."""
        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "warning" not in result.output


# Row 5's corpus: incidents audited, procedures as context, each a folder source.
# `inbox/tickets/`, because the workspace fixture already fills `inbox/incidents/`.
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


class Abstains:
    """Answers every call about the document its `<source_document>` held, abstaining."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        held = re.search(r'<source_document><document key="([^"]+)">', prompt)
        document = held.group(1) if held else ""
        return json.dumps({"document": document, "fields": [abstains(f) for f in FIELDS]})


@pytest.fixture
def procedures(workspace: Path, monkeypatch) -> Path:
    """One incident verified against two procedures, synced and run once."""
    import dossier.cli.main as cli

    for folder, files in (("tickets", TICKETS), ("procedures", PROCEDURES)):
        for name, text in files.items():
            path = workspace / "inbox" / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
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
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    return workspace / "inbox" / "procedures"


class TestARunAfterAProcedureMovedWarns:
    """R4.9 row 5 — a moved reference document is named too, marked as context."""

    def test_a_re_snapshotted_procedure_is_named_as_reference(
        self, workspace: Path, monkeypatch, procedures: Path
    ):
        """The one where `OPS-114` was tightened between two runs."""
        first = sorted(path.name for path in (workspace / "runs").iterdir())[-1]
        (procedures / "OPS-114.md").write_text(
            "# OPS-114 Incident escalation procedure\n\nEscalate within 15 minutes.\n",
            encoding="utf-8",
        )
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[0] == (
            f"warning: the source has moved since run {first}: "
            "OPS-114.md re-snapshotted (reference)"
        )

    def test_a_deleted_procedure_is_named_the_same_way(
        self, workspace: Path, monkeypatch, procedures: Path
    ):
        """The one where `OPS-115` was withdrawn: gone, and still context that moved."""
        first = sorted(path.name for path in (workspace / "runs").iterdir())[-1]
        (procedures / "OPS-115.md").unlink()
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[0] == (
            f"warning: the source has moved since run {first}: OPS-115.md gone (reference)"
        )

    def test_procedures_exactly_as_the_last_run_read_them_print_no_warning(
        self, workspace: Path, monkeypatch, procedures: Path
    ):
        """The one where nothing moved, context included: no warning."""
        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "warning" not in result.output
