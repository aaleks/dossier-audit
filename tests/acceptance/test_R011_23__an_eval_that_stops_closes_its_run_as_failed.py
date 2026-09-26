"""R11.23 — a command that stops after opening its MLflow run closes it as FAILED.
The eval's half.

An eval opens its run before it asks the judge, so the judge's traces sit inside
it (R7.18 row 5). The rule first said an eval recorded its work once it was
done, and a judge nobody could reach left the run `RUNNING`. The unit test
beside this one proves `run` and `calibrate`, whose runs are opened and closed
in the application layer. An eval's are opened and closed by the command, so it
is proved here, through the CLI.

The judge is scripted to fail or be interrupted, and the tracker is a
`FakeTracker` that keeps each run's status, so nothing is reached (R0.1).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeTracker
from tests.scoring_example import PIPELINE

from dossier.infrastructure.models._http import ModelRequestFailed

UNREACHABLE = (
    "POST http://localhost:8080/api/chat/completions failed: "
    "[Errno 111] Connection refused (after 3 attempts)"
)


class StoppedJudge:
    """A judge whose first question stops the command with `stop`."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self, stop: BaseException) -> None:
        self.stop = stop
        self.calls = 0

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        assert "<claim>" in prompt, "eval reproduces the run and asks only the judge"
        self.calls += 1
        raise self.stop


@pytest.fixture
def tracker(monkeypatch) -> FakeTracker:
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


def _judge(monkeypatch, stop: BaseException) -> StoppedJudge:
    import dossier.cli.main as cli

    judge = StoppedJudge(stop)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)
    return judge


class TestAnEvalThatStopsClosesItsRunAsFailed:
    """R11.23 rows 7 to 9 — the eval's record, when the judge stops it."""

    def test_a_judge_nobody_can_reach_leaves_the_eval_run_failed(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Row 7: the one the rule missed.

        The run is closed and the command still fails as R9.20 says it does:
        closing the record is not handling the error.
        """
        workspace, _ = judged_run
        judge = _judge(monkeypatch, ModelRequestFailed(UNREACHABLE))

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert judge.calls == 1
        (run,) = tracker.runs
        assert run.status == "FAILED"
        assert result.exit_code == 2, result.output
        assert f"{PIPELINE}: {UNREACHABLE}" in result.stderr.splitlines()

    def test_an_interrupted_eval_leaves_its_run_failed(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Row 8: the one stopped by a person rather than a model.

        Not a model's failure, so R9.20 does not turn it into a line: the
        interrupt goes on as the terminal always handled it.
        """
        workspace, _ = judged_run
        _judge(monkeypatch, KeyboardInterrupt())

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        (run,) = tracker.runs
        assert run.status == "FAILED"
        # What the terminal does with an interrupt: 128 + SIGINT, and no line.
        assert result.exit_code == 130, result.output
        assert not [line for line in result.stderr.splitlines() if line.startswith(PIPELINE)]

    def test_a_comparison_whose_judge_fails_opened_no_run(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Row 9, a counter-example: the one with nothing to close.

        A comparison opens its run only once both sides are scored (R11.8 row
        4), so a judge that fails on the first side leaves no record at all.
        """
        workspace, first = judged_run
        # Tracking off for the second run, so the only record is the comparison's.
        monkeypatch.delenv("DOSSIER_MLFLOW_ENABLED")
        again = _cli(workspace, monkeypatch, "run", PIPELINE)
        assert again.exit_code == 0, again.output
        second = re.search(r"^run (\S+)", again.output, re.MULTILINE).group(1)
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        _judge(monkeypatch, ModelRequestFailed(UNREACHABLE))

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", first, second
        )

        assert result.exit_code == 2, result.output
        assert tracker.runs == []
