"""R11.36 — a judge's trace that ended in an error closes as ERROR, naming it.

A stage's failed trace closes as ERROR (R11.1 row 4). A judge's closed as OK
whatever happened in it: the eval stopped and its run closed as FAILED, and the
one trace that saw the error said all was well. Over R11.16's judged run, with
a fake tracker, and a judge whose request the client reports refused.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.conftest import GOLD, _cli
from tests.acceptance.test_R011_16__a_judge_verdict_is_an_assessment import (
    JudgingModel,
    judge,
    tracker,
)
from tests.fakes import FakeTracker
from tests.scoring_example import PIPELINE

from dossier.infrastructure.models._http import ModelRequestFailed

REFUSED = "POST http://localhost:8080/api/chat/completions answered 401 Unauthorized"

# R11.16's fixtures, shared rather than copied.
judge, tracker = judge, tracker


def _judge_traces(recorder: FakeTracker) -> list:
    return [trace for trace in recorder.traces if "dossier.field" in trace.tags]


class TestAJudgeTraceThatFailedClosesAsError:
    """R11.36 — ERROR and the error, as a stage's trace closes."""

    def test_a_refused_judge_closes_its_trace_as_error(
        self, judged_run: tuple[Path, str], monkeypatch, judge: JudgingModel, tracker
    ):
        """Row 1 — the one where the judge's request is refused."""
        workspace, _ = judged_run

        def refused(prompt: str, *, schema=None, parts=()) -> str:
            raise ModelRequestFailed(REFUSED)

        monkeypatch.setattr(judge, "complete", refused)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 2, result.output
        (trace,) = _judge_traces(tracker)
        assert (trace.status, trace.error) == ("ERROR", REFUSED)

    def test_an_answered_judge_closes_its_trace_as_ok(
        self, judged_run: tuple[Path, str], monkeypatch, judge: JudgingModel, tracker
    ):
        """Row 2, counter-example — the one the judge answered."""
        workspace, _ = judged_run

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert [trace.status for trace in _judge_traces(tracker)] == ["OK"]
