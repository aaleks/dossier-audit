"""R11.12 — an eval carries a description generated from the figures it printed.

The unit test beside this one proves what a description says. This one proves a
`dossier eval` actually attaches one, and -- the part worth an acceptance test --
that what it says is what the terminal said. Every assertion here reads a figure
out of the command's own output and looks for that same figure in the record.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import FakeTracker, NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

from dossier.application.eval import judge_prompt_hash
from dossier.domain.hashing import text_hash

URI = "http://localhost:5000"
GOLD = "gold/incidents"
NOTE = "mlflow.note.content"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _calibrate(workspace: Path, *, agreement: float = 1.0) -> None:
    gold = workspace / "gold" / "incidents"
    (gold / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    (gold / "calibrations").mkdir(exist_ok=True)
    (gold / "calibrations" / "root_cause.json").write_text(
        json.dumps(
            {
                "judge_model": RoutedModel.model_id,
                "rubric_hash": text_hash(
                    workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"
                ),
                "prompt_hash": judge_prompt_hash(),
                "agreement": agreement,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def scored(workspace: Path, monkeypatch) -> tuple[Path, str]:
    """The four incidents synced and run with tracking off; the run's id."""
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output
    _calibrate(workspace)
    return workspace, re.search(r"^run (\S+)", ran.output, re.MULTILINE).group(1)


@pytest.fixture
def tracker(monkeypatch) -> FakeTracker:
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return recorder


class TestEvalDescribesItselfInMLflow:
    """R11.12 — an eval carries a description generated from the figures printed."""

    def test_the_description_states_the_overall_the_terminal_printed(
        self, scored: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where MLflow and the terminal cannot disagree.

        The percentage is read out of the command's own output and looked for in
        the record. A literal here would let both drift together.
        """
        workspace, run_id = scored

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        printed = re.search(r"overall (\d+\.\d)%", result.output).group(1)
        described = tracker.runs[0].tags[NOTE]
        assert f"overall {printed}%" in described
        assert run_id in described

    def test_the_description_names_the_weakest_field_the_report_marked(
        self, scored: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1, the other figure: the one the report puts an arrow beside."""
        workspace, _ = scored

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        marked = re.search(r"^  (\S+)\s+(\d+\.\d)%.*<- weakest", result.output, re.MULTILINE)
        assert marked, result.output
        assert f"weakest {marked.group(1)} {marked.group(2)}%" in tracker.runs[0].tags[NOTE]

    def test_a_withheld_field_is_named_in_the_description_with_its_reason(
        self, scored: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where the judge is below its bar (R7.15).

        The report prints the reason where a percentage would go, and so does
        the description. The two saying different things about one field is what
        spec 011 exists to prevent.
        """
        workspace, _ = scored
        _calibrate(workspace, agreement=0.5)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        described = tracker.runs[0].tags[NOTE]
        assert "withheld root_cause" in described
        assert "root_cause 50.0%" not in described

    def test_tracking_a_description_changes_nothing_on_disk(
        self, scored: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 5): the one where the record is not an input.

        The manifest of the scored run is read before and after. A description is
        a record, and R10.4 says a record changes nothing a run produced.
        """
        workspace, run_id = scored
        manifest = workspace / "runs" / run_id / "manifest.json"
        before = manifest.read_bytes()

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].tags[NOTE], "a description was written"
        assert manifest.read_bytes() == before
