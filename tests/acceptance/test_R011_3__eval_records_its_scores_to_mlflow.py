"""R11.3 — a `dossier eval` is one MLflow run with one metric per scored field.

The unit test beside this one proves what the record *contains*. This one proves
a `dossier eval` *makes* one, which is the rule's Given and what nothing proved
until `/verify` found that `record_eval` had no caller anywhere in `src/`: the
command scored, printed, and recorded nothing at all.

Rows 1 and 2 live here, because they are the two a person can observe by running
the command. Rows 3 and 4 -- a judge's agreement, and a judge below its threshold
-- stay in the unit test: no pipeline configures a judge threshold yet, so there
is no way to reach them from the CLI without inventing configuration no rule
describes.

Tracking is switched on the way a person switches it on, in the environment
(R10.1), and only *after* the sync and the run, so the one MLflow run under test
is the eval. The CLI is handed a `FakeTracker` through the same seam
`build_model_client` uses.
"""

from __future__ import annotations

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

URI = "http://localhost:5000"
GOLD = "gold/incidents"

# R11.3 example 1, transcribed. The same figures R7.2 prints, as percentages and
# not proportions, so the terminal and MLflow cannot disagree (spec 011).
EXPECTED = {
    "accuracy/loss_amount": 100.0,
    "accuracy/resolution_date": 75.0,
    "accuracy/severity": 100.0,
    "accuracy/affected_systems": 75.0,
    "accuracy/root_cause": 50.0,
    "accuracy/overall": 80.0,
}


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> tuple[Path, str]:
    """The four documents synced and run, with tracking still off; the run's id.

    Off on purpose: `dossier run` records too (R11.1), and a tracker switched on
    before it would hold two runs, leaving every assertion below about the wrong
    one.
    """
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output

    found = re.search(r"^run (\S+)", ran.output, re.MULTILINE)
    assert found, ran.output
    return workspace, found.group(1)


@pytest.fixture
def tracker(audited: tuple[Path, str], monkeypatch) -> FakeTracker:
    """Tracking switched on after the run, recording to a fake that counts."""
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    # Scoring asks no model: every field in this gold set is scored without a
    # judge (R7.10), so a call here would be a finding rather than a cost.
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return recorder


class TestEvalRecordsItsScoresToMLflow:
    """R11.3 — a `dossier eval` is one MLflow run with one metric per scored field."""

    def test_an_eval_is_one_mlflow_run_with_the_accuracy_it_prints_per_field(
        self, audited: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one over the scoring example.

        One run, and the five fields plus the overall the report prints. The
        command exiting 0 is not the claim -- it did that before this rule was
        wired, while recording nothing.
        """
        workspace, _ = audited

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1, "one eval is one MLflow run"
        assert tracker.runs[0].metrics == EXPECTED

    def test_the_eval_names_its_model_its_gold_set_and_the_run_it_scored(
        self, audited: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one read back for what was scored, against what.

        The gold set is named and tagged with a full 64-character hash of its
        contents (R0.7), and the run it scored is tagged by id -- so an eval can
        be followed back to the run it measured, and two evals over gold sets
        that differ by one answer are told apart.
        """
        workspace, run_id = audited

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        run = tracker.runs[0]
        assert run.params == {"model": RoutedModel.model_id, "gold": "incidents"}
        assert run.tags["dossier.run_id"] == run_id
        assert run.tags["dossier.kind"] == "eval"
        assert re.fullmatch(r"[0-9a-f]{64}", run.tags["dossier.gold_hash"])
