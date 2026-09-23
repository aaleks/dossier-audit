"""R10.14 — a namespace MLflow would reject is refused before any work.

R14.10's test, reclaimed for the variable that replaced R14.8's. The namespace
goes in front of every prompt name, which MLflow refuses `/` and `:` in, so a
namespace holding either is refused where the rest of this machine's tracking
settings are -- before anything is fetched, asked or recorded -- by every command
that records, `dataset publish` included although a dataset name alone could have
held the character.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.acceptance.test_R014_9__a_judge_links_the_rubric_version_it_judged_with import (
    VERDICTS,
    _calibratable,
)
from tests.fakes import (
    FakeDatasetRegistry,
    FakeModelClient,
    FakePromptRegistry,
    FakeTracker,
    register_connector,
)
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

pytestmark = pytest.mark.outer_loop

PREFIX = "DOSSIER_MLFLOW_NAMESPACE"


class CountingTracker(IssueTracker):
    """The scoring example's source, counting what it is asked to fetch."""

    fetched: list[str] = []

    def fetch(self, key: str):
        self.fetched.append(key)
        return super().fetch(key)


def _wire(monkeypatch, *, prefix: str = "team/a") -> FakeTracker:
    """Tracking on, a tracker that counts runs, and the prefix under test."""
    import dossier.cli.main as cli

    tracker = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setenv(PREFIX, prefix)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: FakePromptRegistry(), raising=False
    )
    return tracker


def _declared(workspace: Path, monkeypatch) -> Path:
    """The scoring example's incidents, declared and synced with tracking off."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


def _model(monkeypatch, model):
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return model


def _refused(result) -> None:
    assert result.exit_code == 2, result.output
    assert PREFIX in result.output, "the refusal names the setting to change"
    assert "'/'" in result.output, "and the character MLflow rejects"


class TestANamespaceMlflowWouldRejectIsRefusedBeforeAnyWork:
    """R10.14 — refused before any work by every command that records."""

    def test_an_eval_is_refused_before_the_judge_is_asked(self, judged_run, monkeypatch):
        """Row 1: the one that raised a traceback."""
        workspace, _ = judged_run
        model = _model(monkeypatch, RoutedModel({}))
        tracker = _wire(monkeypatch)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        _refused(result)
        assert model.call_count == 0, "no judge was asked"
        assert tracker.runs == [], "and no MLflow run was opened"

    def test_a_calibration_is_refused_before_the_judge_is_asked(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one that raised a traceback and left its run open."""
        calibratable = _calibratable(workspace, monkeypatch)
        judge = _model(
            monkeypatch,
            FakeModelClient(responses=[json.dumps({"supported": v}) for v in VERDICTS]),
        )
        tracker = _wire(monkeypatch)

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        _refused(result)
        assert judge.call_count == 0
        assert tracker.runs == []

    def test_a_run_is_refused_before_its_record_opens(self, workspace: Path, monkeypatch):
        """Row 3: the one refused through the wrong handler, after its run was open."""
        declared = _declared(workspace, monkeypatch)
        model = _model(monkeypatch, RoutedModel(ANSWERS))
        tracker = _wire(monkeypatch)

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        _refused(result)
        assert model.call_count == 0
        assert tracker.runs == [], "refused before the run opens, not after"

    def test_a_sync_is_refused_before_anything_is_fetched(self, workspace: Path, monkeypatch):
        """Row 4: the one where the setting is refused where it is read."""
        (workspace / "sources.yaml").write_text(
            f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
        )
        write_pipeline(workspace, sources=[SOURCE_ID])
        source = CountingTracker(ISSUES)
        source.fetched = []
        register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: source)
        tracker = _wire(monkeypatch)

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        _refused(result)
        assert source.fetched == [], "0 items fetched"
        assert tracker.runs == []

    def test_a_dataset_publish_is_refused_before_anything_is_sent(
        self, workspace: Path, monkeypatch
    ):
        """Row 5: the one refused although a dataset name would have taken the `/`.

        One namespace goes in front of every published name, and the name it
        cannot go in front of decides.
        """
        import dossier.cli.main as cli

        write_pipeline(workspace, sources=[SOURCE_ID])
        datasets = FakeDatasetRegistry()
        monkeypatch.setattr(
            cli, "build_dataset_registry", lambda settings: datasets, raising=False
        )
        _wire(monkeypatch)

        result = _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)

        _refused(result)
        assert datasets.datasets == {}, "0 datasets created"

    def test_tracking_off_reads_no_prefix(self, workspace: Path, monkeypatch):
        """Counter-example (row 6): the one where nothing would send or look up a name."""
        declared = _declared(workspace, monkeypatch)
        _model(monkeypatch, RoutedModel(ANSWERS))
        _wire(monkeypatch)
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "false")

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output

    def test_a_prefix_mlflow_accepts_refuses_nothing(self, workspace: Path, monkeypatch):
        """Counter-example (row 7): the one where the namespace is fine (R10.13 row 1)."""
        declared = _declared(workspace, monkeypatch)
        _model(monkeypatch, RoutedModel(ANSWERS))
        tracker = _wire(monkeypatch, prefix="sandbox")

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1, "and the run recorded as it always does"
