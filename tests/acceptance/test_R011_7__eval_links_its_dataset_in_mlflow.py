"""R011.7 — a `dossier eval` links its MLflow run to the dataset of the gold set it
scored, and names a stale one.

The link is what makes an eval run and the answers it was measured against one
click apart instead of one hash lookup. It is a record and never an input: what
was scored is the gold set on disk (R12.4), so a dataset that does not match it is
*named*, and a dataset that cannot be read at all costs the eval nothing (R10.6).

What a person observes by running the two commands. Four ways the dataset can
stand in relation to the eval — matching, stale, absent,
unreadable — and the command exits 0 with the same scores in all four.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import FakeDatasetRegistry, FakeTracker, NoModelClient, register_connector
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

GOLD = "gold/incidents"
URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """The four documents synced and run, with tracking off so only the eval records."""
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output

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
                "agreement": 1.0,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return workspace


@pytest.fixture
def recording(audited: Path, monkeypatch) -> tuple[FakeTracker, FakeDatasetRegistry]:
    """Tracking on after the run, with a tracker and a registry that both count."""
    import dossier.cli.main as cli

    tracker, registry = FakeTracker(), FakeDatasetRegistry()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: registry)
    return tracker, registry


def _publish(workspace: Path, monkeypatch):
    result = _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)
    assert result.exit_code == 0, result.output
    return result


def _edit_gold(workspace: Path) -> None:
    """One answer corrected after publishing, so the two hashes part company."""
    path = workspace / "gold" / "incidents" / "INC-4821.json"
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["fields"]["severity"] = {"value": "minor"}
    path.write_text(json.dumps(edited, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestAnEvalLinksTheDatasetItScoredAgainst:
    """R11.7 — an eval links its run to the dataset, and names a stale one."""

    def test_the_eval_run_carries_the_dataset_it_was_measured_against(
        self, audited: Path, monkeypatch, recording
    ):
        """Example 1: the one where the dataset matches what was scored.

        The dataset is an input of the eval run, so a person reading the run in
        MLflow can open the answers behind the figures without knowing a hash.
        """
        tracker, registry = recording
        _publish(audited, monkeypatch)

        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert run.inputs == [
            {
                "name": "incidents",
                "dataset_id": registry.find("incidents").dataset_id,
                "digest": registry.find("incidents").digest,
            }
        ]
        assert "dossier.dataset_stale" not in run.tags

    def test_a_gold_set_edited_since_publishing_is_linked_and_named_stale(
        self, audited: Path, monkeypatch, recording
    ):
        """Example 2: the one where the dataset is behind the answers that were scored.

        Linked anyway and tagged stale, with both hashes, because the figures are
        the edited set's and refusing would let a tracking server block a score
        computed entirely from local files (R10.6). The terminal says which hash is
        which and what to run.
        """
        tracker, registry = recording
        _publish(audited, monkeypatch)
        published_hash = registry.find("incidents").tags["dossier.gold_hash"]
        _edit_gold(audited)

        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert run.tags["dossier.dataset_stale"] == "true"
        scored_hash = run.tags["dossier.gold_hash"]
        assert scored_hash != published_hash
        assert published_hash[:8] in result.output
        assert scored_hash[:8] in result.output
        assert "dossier dataset publish" in result.output
        assert run.inputs, "still linked: the dataset is the one this gold set has"

    def test_an_unpublished_gold_set_records_everything_else_and_no_input(
        self, audited: Path, monkeypatch, recording
    ):
        """Example 3: the one where nobody has published this gold set.

        Not an error and not a warning worth an exit code: the eval records what
        R11.3 says it records, and simply has nothing to link.
        """
        tracker, _ = recording

        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert run.inputs == []
        assert run.metrics["accuracy/overall"] == 80.0, "the figures are untouched"

    def test_a_dataset_that_cannot_be_read_costs_the_eval_nothing(
        self, audited: Path, monkeypatch, recording
    ):
        """Example 4: the one where the dataset call fails and the run's calls do not.

        A lost record never changes a command's outcome (R10.6). The eval scores,
        records its metrics, says the link could not be made, and exits 0.
        """
        tracker, registry = recording
        _publish(audited, monkeypatch)

        def unreadable(name: str):
            raise RuntimeError("500 Server Error")

        monkeypatch.setattr(registry, "find", unreadable)

        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert run.inputs == []
        assert run.metrics["accuracy/overall"] == 80.0
        assert "dataset" in result.output.lower()

    def test_a_comparison_links_nothing_because_it_records_nothing(
        self, audited: Path, monkeypatch, recording
    ):
        """Counter-example (row 5): the one where there is no run to link to.

        A comparison reads two runs that were each recorded when they ran (R7.8),
        so it opens no MLflow run — and a link needs one.
        """
        tracker, _ = recording
        _publish(audited, monkeypatch)
        ran = _cli(audited, monkeypatch, "run", PIPELINE)
        assert ran.exit_code == 0, ran.output
        runs = sorted(path.name for path in (audited / "runs").iterdir() if path.is_dir())
        assert len(runs) >= 2, runs
        before = len(tracker.runs)

        result = _cli(
            audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", *runs[:2]
        )

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == before, "a comparison records no run"
