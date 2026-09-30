"""R11.28 — a `dossier gc --apply` is one MLflow run of what it deleted, in
`dossier-audit/gc`; a preview records nothing.

`gc` is the first command with no pipeline, so its default experiment drops the
pipeline from R10.2's default template, and a template naming `{pipeline}` is
refused for it, as one naming `{gold}` is for a sync (R10.2 row 5).
`collected.json` names each run deleted, so a run whose record is still in
MLflow can be traced to the `gc` that removed its files.

Through the CLI, tracking on and a `FakeTracker`, over R16.1 row 1's workspace:
three runs of `incident-audit` and a try; `--keep-last 2`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R016_1__a_kept_run_replays_after_gc import (
    _files,
    _no_model,
    _three_runs_and_a_try,
)
from tests.fakes import FakeTracker

URI = "http://localhost:5000"
FREED = r"freed (\d+\.\d) MB: 1 run, 1 try, 0 replays, (\d+) cache entries"


def _tracked(workspace: Path, monkeypatch, *, experiment: str | None = None) -> FakeTracker:
    import dossier.cli.bootstrap as cli

    tracker = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    if experiment is not None:
        monkeypatch.setenv("DOSSIER_MLFLOW_EXPERIMENT", experiment)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    return tracker


def _gc(workspace: Path, monkeypatch, *more: str):
    return _cli(workspace, monkeypatch, "gc", "--keep-last", "2", *more)


class TestGcRecordsWhatItDeleted:
    """R11.28 — one run in `dossier-audit/gc` per `gc --apply` that deleted something."""

    def test_an_apply_is_one_run_of_its_counts(self, workspace: Path, monkeypatch):
        """Row 1 — the one that deleted a run, a try and the entries only it read."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        tracker = _tracked(workspace, monkeypatch)

        result = _gc(workspace, monkeypatch, "--apply")

        assert result.exit_code == 0, result.output
        megabytes, entries = re.fullmatch(FREED, result.output.splitlines()[0]).groups()
        (run,) = tracker.runs
        assert run.experiment == "dossier-audit/gc"
        assert re.fullmatch(r"gc \d{8}T\d{6}Z", run.name), run.name
        assert run.tags["dossier.kind"] == "gc"
        assert run.tags["dossier.pipeline"] == ""
        assert run.metrics == {
            "runs": 1,
            "tries": 1,
            "replays": 0,
            "entries": int(entries),
            "megabytes": float(megabytes),
        }
        assert run.params["keep_last"] == "2"
        assert run.traces == []

    def test_the_runs_deleted_are_named(self, workspace: Path, monkeypatch):
        """Row 2 — the one whose `collected.json` names the run and its pipeline."""
        oldest, *_ = _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        tracker = _tracked(workspace, monkeypatch)

        assert _gc(workspace, monkeypatch, "--apply").exit_code == 0

        (run,) = tracker.runs
        assert json.loads(run.artifacts["collected.json"]) == [
            {"run": oldest, "pipeline": "incident-audit"}
        ]

    def test_a_template_naming_the_pipeline_is_refused(self, workspace: Path, monkeypatch):
        """Row 3 — the one where the shared template has a `{pipeline}` gc cannot fill."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        before = _files(workspace)
        tracker = _tracked(workspace, monkeypatch, experiment="team/{pipeline}/{kind}")

        result = _gc(workspace, monkeypatch, "--apply")

        assert result.exit_code == 2, result.output
        assert "DOSSIER_MLFLOW_EXPERIMENT_GC" in result.stderr, result.stderr
        assert _files(workspace) == before
        assert tracker.runs == []

    def test_a_preview_records_nothing(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one that deleted nothing, by design."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        tracker = _tracked(workspace, monkeypatch)

        assert _gc(workspace, monkeypatch).exit_code == 0

        assert tracker.runs == []

    def test_an_apply_with_nothing_to_collect_records_nothing(
        self, workspace: Path, monkeypatch
    ):
        """Row 5, counter-example — the one run again after everything went."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        assert _gc(workspace, monkeypatch, "--apply").exit_code == 0
        tracker = _tracked(workspace, monkeypatch)

        result = _gc(workspace, monkeypatch, "--apply")

        assert result.output.splitlines() == ["nothing to collect"], result.output
        assert tracker.runs == []

    def test_the_terminal_says_where_it_was_recorded(self, workspace: Path, monkeypatch):
        """Row 6 — the one ending with the line `eval` and `calibrate` end with."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        _tracked(workspace, monkeypatch)

        result = _gc(workspace, monkeypatch, "--apply")

        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1] == "recorded to MLflow: dossier-audit/gc"

    def test_nothing_recorded_is_not_said_to_be(self, workspace: Path, monkeypatch):
        """Row 7, counter-example — the one with tracking off."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)

        result = _gc(workspace, monkeypatch, "--apply")

        assert result.exit_code == 0, result.output
        assert "recorded to MLflow" not in result.output
