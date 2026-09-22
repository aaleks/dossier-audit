"""R11.11 — an eval records the version of everything it scored.

The unit test beside this one proves what the params hold. This one proves an
eval actually reads them off the manifest of the run it reproduced -- which is
the whole claim, because the alternative anyone would reach for is recomputing
them from the pipeline on disk, and that describes the scoring machine rather
than the run (R4.9).
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


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _calibrate(workspace: Path) -> str:
    """A measured judge, so `root_cause` is reported; returns the rubric's hash."""
    gold = workspace / "gold" / "incidents"
    rubric = text_hash(workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md")
    (gold / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    (gold / "calibrations").mkdir(exist_ok=True)
    (gold / "calibrations" / "root_cause.json").write_text(
        json.dumps(
            {
                "judge_model": RoutedModel.model_id,
                "rubric_hash": rubric,
                "prompt_hash": judge_prompt_hash(),
                "agreement": 1.0,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return rubric


@pytest.fixture
def scored(workspace: Path, monkeypatch) -> tuple[Path, str, str]:
    """The four incidents synced and run, tracking off; the run id and rubric hash."""
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
    rubric = _calibrate(workspace)
    return workspace, re.search(r"^run (\S+)", ran.output, re.MULTILINE).group(1), rubric


@pytest.fixture
def tracker(monkeypatch) -> FakeTracker:
    """Tracking on after the run, so the only record under test is the eval's."""
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return recorder


class TestEvalRecordsWhatProducedWhatItScored:
    """R11.11 — an eval records the version of everything it scored."""

    def test_the_eval_names_the_pipeline_prompt_and_converters_of_the_run_it_scored(
        self, scored: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where a figure finally has a stated cause.

        Every value is compared against the manifest on disk rather than against
        a literal, because the claim is that they were *read from it*.
        """
        workspace, run_id, _ = scored
        manifest = json.loads(
            (workspace / "runs" / run_id / "manifest.json").read_text(encoding="utf-8")
        )

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        recorded = tracker.runs[0].params
        assert recorded["pipeline_hash"] == manifest["plan"]["pipeline_hash"]
        assert recorded["documents"] == str(len(manifest["plan"]["documents"]))
        for step in manifest["plan"]["steps"]:
            assert recorded[f"prompt/{step['id']}"] == step["prompt_hash"]
        assert recorded["converters"] == ", ".join(
            sorted(f"{c['id']} {c['version']}" for c in manifest["plan"]["converters"])
        )

    def test_the_eval_says_which_dossier_made_the_run_and_when(
        self, scored: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1, the other half: the two values that are about the run, not the plan.

        They sit beside the plan's on purpose. A figure that moved between two
        evals of the same pipeline hash is a dossier version or a re-run, and
        neither is visible from the plan alone.
        """
        workspace, run_id, _ = scored
        manifest = json.loads(
            (workspace / "runs" / run_id / "manifest.json").read_text(encoding="utf-8")
        )

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        recorded = tracker.runs[0].params
        assert recorded["dossier_version"] == manifest["dossier_version"]
        assert recorded["scored_at"] == manifest["started_at"]

    def test_a_judged_field_records_the_rubric_it_was_judged_against(
        self, scored: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where a rubric edit becomes visible on the eval that used it.

        The model and the agreement are already recorded (R11.3 row 3). Without
        the rubric beside them, an edit to the standard the judge applies moves
        the figure and leaves no trace on the record that reports it.
        """
        workspace, _, rubric = scored

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].params["judge/root_cause/rubric"] == rubric

    def test_nothing_recorded_is_recomputed_from_the_pipeline_on_disk(
        self, scored: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 5): the one where the pipeline moved after the run.

        The prompt is edited between the run and the eval. What is recorded is
        still what the run used -- otherwise the record would describe the
        pipeline as it is today and attribute today's prompt to yesterday's
        answers.
        """
        workspace, run_id, _ = scored
        manifest = json.loads(
            (workspace / "runs" / run_id / "manifest.json").read_text(encoding="utf-8")
        )
        prompt = workspace / "pipelines" / PIPELINE / "prompts" / "01_extract.md"
        prompt.write_text(
            prompt.read_text(encoding="utf-8") + "\n\nEdited.\n", encoding="utf-8"
        )

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        pinned = manifest["plan"]["steps"][0]
        assert tracker.runs[0].params[f"prompt/{pinned['id']}"] == pinned["prompt_hash"]
        assert text_hash(prompt) != pinned["prompt_hash"], "the edit really moved the hash"
