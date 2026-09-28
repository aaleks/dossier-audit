"""R6.24 row 1, through `dossier run` — the declaration is what says a field may repeat.

The unit test hands `run_stage` its list fields directly. This one declares them,
so it fails if the run ever stops carrying the declaration's lists to the check
on the reply: a two-system answer would then be refused as two answers to one
question, and every list in every pipeline would fail.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes import register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, IssueTracker, RoutedModel, found

PIPELINE = "incident-audit"
SOURCE_TYPE = "issue-tracker"

BOTH = {
    "INC-4821": [
        found("INC-4821", "affected_systems", "payments-api", "payments-api"),
        found("INC-4821", "affected_systems", "ledger-batch", "ledger-batch"),
    ]
}


def _ran(workspace: Path, monkeypatch, kind: str):
    from typer.testing import CliRunner

    import dossier.cli.bootstrap as cli
    from dossier.cli.main import app

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: incidents-jira\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["incidents-jira"],
        outputs={"extract": "schemas/incident.yaml"},
        write_declaration=False,
    )
    (workspace / "pipelines" / PIPELINE / "schemas" / "incident.yaml").write_text(
        f"fields:\n  affected_systems: {{kind: {kind}}}\n", encoding="utf-8"
    )
    register_connector(
        monkeypatch,
        SOURCE_TYPE,
        lambda config, *, workspace: IssueTracker({"INC-4821": ISSUES["INC-4821"]}),
    )
    # The same answer however often it is asked, so a retry is visible as a call.
    model = RoutedModel(BOTH)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    monkeypatch.chdir(workspace)
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = CliRunner().invoke(app, list(args))
    return result, model


class TestADeclaredListReachesTheReplyCheck:
    """R6.24 — only a field the declaration calls a `list` may repeat."""

    def test_a_declared_list_answered_twice_stands(self, workspace: Path, monkeypatch):
        """Row 1 — the one where the declaration says `list`."""
        result, model = _ran(workspace, monkeypatch, "list")

        assert result.exit_code == 0, result.output
        assert "failed" not in result.output.replace("0 failed", ""), result.output
        assert model.call_count == 1

    def test_the_same_answer_to_a_reference_is_refused(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one where the same two records answer a `reference`."""
        result, model = _ran(workspace, monkeypatch, "reference")

        assert "1 failed" in result.output and "INC-4821" in result.output, result.output
        # Asked, refused, asked again with the refusal, refused again (R6.2).
        assert model.call_count == 2
