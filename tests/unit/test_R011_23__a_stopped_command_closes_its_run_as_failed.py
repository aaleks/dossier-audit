"""R11.23 — a command that stops after opening its MLflow run closes it as FAILED.

A run left `RUNNING` reads as a command still at work, forever. Found live: a
calibration whose model was unreachable left an empty run on the server, named
as if it were measuring. Three commands open their run before the work they
record -- `run`, `calibrate` and `eval` -- so those are the three that can stop
with one open; the others record their work once it is done. The first two open
and close theirs in the application layer and are proved here. An eval's are
opened and closed by the command, so rows 7 to 9 are proved through the CLI, in
`tests/acceptance/`.

The model is scripted to fail, or to be interrupted, and the tracker is a
`FakeTracker` that keeps each run's status. What stopped the command must still
be what the command fails with: closing the record is not handling the error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

from dossier.domain.gold import CalibrationCase
from dossier.domain.judges import NotCalibrated
from dossier.infrastructure.models.openai_compatible import ModelRequestFailed

MODEL = "anthropic:claude-sonnet-4-5-20250929"
RUBRIC = "Is the stated root cause supported by the named document?\n"
URI = "http://localhost:5000"
UNREACHABLE = (
    "POST http://127.0.0.1:8114/api/chat/completions failed: [WinError 10061] "
    "No connection could be made because the target machine actively refused it"
)


class StoppingModel:
    """Answers the reviewer's verdict for `answered` calls, then raises `stop`."""

    model_id = MODEL

    def __init__(self, answered: int, stop: BaseException) -> None:
        self.answered = answered
        self.stop = stop
        self.calls = 0

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.calls += 1
        if self.calls > self.answered:
            raise self.stop
        return json.dumps({"supported": True})


class ClosingFails(FakeTracker):
    """A tracker whose server is gone by the time the run is closed."""

    def end_run(self, *, status: str) -> None:
        raise ConnectionError("the tracking server went away")


def _cases(count: int = 20) -> list[CalibrationCase]:
    return [
        CalibrationCase(
            document=f"INC-{4800 + index}",
            answer=f"candidate answer {index}",
            supported=True,
            verified_by="a.aleks",
            verified_at="2026-09-15",
        )
        for index in range(count)
    ]


def _calibrate(model, tracker: FakeTracker, tmp_path: Path, *, cases=None):
    from dossier.application.eval import FieldSample, calibrate_fields

    cases = _cases() if cases is None else cases
    return calibrate_fields(
        model,
        directory=tmp_path,
        samples={"root_cause": FieldSample(cases=cases, rubric=RUBRIC, rubric_hash="f7a2d9c4")},
        documents={case.document: f"The text of {case.document}." for case in cases},
        judge_model=MODEL,
        tracker=tracker,
        experiment="dossier-audit/incident-audit/calibrate",
        pipeline="incident-audit",
    )


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _tracked(workspace: Path, monkeypatch, source) -> FakeTracker:
    """The scoring example's workspace, with tracking on and recording to a fake."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: source)
    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


class InterruptedSource(IssueTracker):
    """A source that is interrupted while it is being listed."""

    def list(self, since=None):
        raise KeyboardInterrupt


class TestAStoppedCommandClosesItsRunAsFailed:
    """R11.23 — no command leaves its run RUNNING."""

    def test_a_calibration_whose_judge_is_unreachable_ends_failed(self, tmp_path: Path):
        """Row 1: the one from the live check -- the judge unreachable on the first case."""
        tracker = FakeTracker()

        with pytest.raises(ModelRequestFailed, match="actively refused"):
            _calibrate(StoppingModel(0, ModelRequestFailed(UNREACHABLE)), tracker, tmp_path)

        (run,) = tracker.runs
        assert run.status == "FAILED"
        assert not (tmp_path / "calibrations").exists(), "nothing was measured"

    def test_an_interrupted_calibration_ends_failed_and_the_interrupt_goes_on(
        self, tmp_path: Path
    ):
        """Row 2: the one interrupted on the eleventh case.

        Ten cases were judged and their ten traces recorded; the run holds them,
        closed as FAILED, and the interrupt reaches whoever pressed Ctrl-C.
        """
        tracker = FakeTracker()

        with pytest.raises(KeyboardInterrupt):
            _calibrate(StoppingModel(10, KeyboardInterrupt()), tracker, tmp_path)

        (run,) = tracker.runs
        assert run.status == "FAILED"
        assert len(run.traces) == 10

    def test_a_run_whose_model_is_unreachable_ends_failed(self, workspace: Path, monkeypatch):
        """Row 3: `dossier run`, the model unreachable -- true of the code, now stated."""
        import dossier.cli.bootstrap as cli

        _cli(workspace, monkeypatch, "sync", PIPELINE)
        tracker = _tracked(workspace, monkeypatch, IssueTracker(ISSUES))
        synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
        assert synced.exit_code == 0, synced.output
        tracker.runs.clear()
        monkeypatch.setattr(
            cli,
            "build_model_client",
            lambda model_id: StoppingModel(0, ModelRequestFailed(UNREACHABLE)),
        )

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code != 0
        (run,) = tracker.runs
        assert run.status == "FAILED"

    def test_an_interrupted_sync_leaves_no_run_at_all(self, workspace: Path, monkeypatch):
        """Row 4, counter-example: the one where the run was never opened.

        A sync opens its run once its sources have answered, to record their
        counts (R11.4). Interrupted inside a source, it had opened nothing, so
        there is nothing left RUNNING and nothing to close.
        """
        tracker = _tracked(workspace, monkeypatch, InterruptedSource(ISSUES))

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code != 0
        assert tracker.runs == []

    def test_a_refused_calibration_opens_no_run(self, tmp_path: Path):
        """Row 5, counter-example: 19 cases, refused before a run was opened (R11.5 row 4)."""
        tracker = FakeTracker()

        with pytest.raises(NotCalibrated):
            _calibrate(
                StoppingModel(19, KeyboardInterrupt()), tracker, tmp_path, cases=_cases(19)
            )

        assert tracker.runs == []

    def test_a_failure_to_close_never_replaces_what_stopped_the_command(self, tmp_path: Path):
        """Row 6, counter-example: the server gone by the time the run is closed.

        The command fails with the model's error, not the tracker's: a lost
        record never changes a command's outcome (R10.6).
        """
        with pytest.raises(ModelRequestFailed, match="actively refused"):
            _calibrate(
                StoppingModel(0, ModelRequestFailed(UNREACHABLE)), ClosingFails(), tmp_path
            )
