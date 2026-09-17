"""R7.18 — a judge verdict is cached, and the judge is asked only on a miss. The
CLI half.

The unit test beside this one proves the key and the cache. This one proves
what a person running the commands observes: a second eval asks nothing, a
comparison over the same candidate asks nothing, a tracked eval leaves one
trace per judged (document, field) with an LLM span only where the judge was
asked, and `--plan` and `--replay` never ask at all.

The workspace is R7.17's: the scoring example's four documents and `INC-4830`,
whose stated root cause is the one field a judge decides. The judge is a
`FakeModelClient` that counts calls, or `NoModelClient`, which fails on any.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.test_R007_17__eval_scores_free_text_with_the_judge import (
    RC_01,
    _answers,
    _calibrated,
    _cli,
    _eval,
    _judge,
    _run,
    _verdict,
    held,  # noqa: F401 -- the fixture, re-exported for pytest to find
)
from tests.fakes import FakeTracker, NoModelClient
from tests.scoring_example import ANSWERS_AFTER, PIPELINE

URI = "http://localhost:5000"


@pytest.fixture
def judged(held: Path, monkeypatch) -> Path:  # noqa: F811 -- the imported fixture
    """A run over the five documents, the judge calibrated, and one eval already made.

    The first eval asks the judge once -- row 1, proved in the unit test -- and
    leaves the verdict behind for the rows here.
    """
    _run(held, monkeypatch, _answers(RC_01, span=RC_01))
    _calibrated(held)
    judge = _judge(monkeypatch, _verdict(True, "stated"))
    first = _eval(held, monkeypatch)
    assert first.exit_code == 0, first.output
    assert judge.call_count == 1
    return held


def _no_judge(monkeypatch) -> None:
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())


def _tracked(monkeypatch) -> FakeTracker:
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


class TestEvalAsksTheJudgeOnlyOnAMiss:
    """R7.18 — a judge is a model, and a model is asked only on a cache miss (R0.10)."""

    def test_the_same_eval_again_asks_nothing(self, judged: Path, monkeypatch):
        """Example 2: the one served from cache, with the same figure.

        A judge that fails on any call is the assertion; the percentage is the
        same one the first eval printed (R5.5).
        """
        _no_judge(monkeypatch)

        result = _eval(judged, monkeypatch)

        assert result.exit_code == 0, result.output
        assert "60.0%" in result.output and "(1 judged)" in result.output

    def test_a_comparison_over_the_same_candidate_asks_nothing(self, judged: Path, monkeypatch):
        """Example 3: the one where run `b` answered `INC-4830` exactly as run `a` did.

        The prompt moved, so `b` is a different run with a different stage key
        -- and the same candidate, so the same judge key. Two runs, one verdict,
        zero calls.
        """
        prompt = judged / "pipelines" / PIPELINE / "prompts" / "extract.md"
        prompt.write_text(
            "Read carefully.\n" + prompt.read_text(encoding="utf-8"), encoding="utf-8"
        )
        b = _run(
            judged,
            monkeypatch,
            {**ANSWERS_AFTER, "INC-4830": _answers(RC_01, span=RC_01)["INC-4830"]},
        )
        _no_judge(monkeypatch)

        result = _eval(judged, monkeypatch, "--compare", _latest_before(judged, b), b)

        assert result.exit_code == 0, result.output
        line = next(line for line in result.output.splitlines() if "root_cause" in line)
        assert "60.0%" in line, line

    def test_a_tracked_eval_leaves_one_trace_per_judged_field(self, judged: Path, monkeypatch):
        """Example 5: the one where the verdict is served from cache under tracking.

        One trace on the eval's run, tagged with the document and the field,
        and no LLM span in it: seeing that a verdict cost nothing is
        information (R11.2 row 3's shape). A miss would hold one.
        """
        tracker = _tracked(monkeypatch)
        _no_judge(monkeypatch)

        result = _eval(judged, monkeypatch)

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1, "one eval is one MLflow run"
        traces = tracker.runs[0].traces
        assert [(t.tags["dossier.document"], t.tags["dossier.field"]) for t in traces] == [
            ("INC-4830", "root_cause")
        ]
        assert [span for span in traces[0].spans if span["kind"] == "llm"] == []
        assert tracker.runs[0].metrics["accuracy/root_cause"] == 60.0

    def test_a_tracked_miss_holds_one_llm_span(self, held: Path, monkeypatch):  # noqa: F811
        """Example 5, the other half: the one where the judge was asked.

        The first eval, tracked: the same one trace, holding exactly one LLM
        span -- the trace and the judge's call count are the same claim seen
        twice (R11.2).
        """
        _run(held, monkeypatch, _answers(RC_01, span=RC_01))
        _calibrated(held)
        tracker = _tracked(monkeypatch)
        judge = _judge(monkeypatch, _verdict(True, "stated"))

        result = _eval(held, monkeypatch)

        assert result.exit_code == 0, result.output
        (trace,) = tracker.runs[0].traces
        assert (
            len([span for span in trace.spans if span["kind"] == "llm"])
            == 1
            == judge.call_count
        )

    def test_a_plan_and_a_replay_never_ask_the_judge(self, judged: Path, monkeypatch):
        """Counter-example (row 6): the ones that make nothing new.

        `--plan` records and computes nothing (R4.6); `--replay` reproduces a
        record (R4.7). Neither scores, so neither has a verdict to read or a
        judge to ask.
        """
        run_id = _latest_run(judged)
        _no_judge(monkeypatch)

        planned = _cli(judged, monkeypatch, "run", PIPELINE, "--plan")
        replayed = _cli(judged, monkeypatch, "run", PIPELINE, "--replay", f"runs/{run_id}")

        assert planned.exit_code == 0, planned.output
        assert replayed.exit_code == 0, replayed.output


def _latest_run(workspace: Path) -> str:
    """The latest run's id, from the run directory: run ids sort by their timestamp."""
    return sorted(path.name for path in (workspace / "runs").iterdir())[-1]


def _latest_before(workspace: Path, run_id: str) -> str:
    """The run made before `run_id`: the fixture's, so the comparison spans both."""
    runs = sorted(path.name for path in (workspace / "runs").iterdir())
    return runs[runs.index(run_id) - 1]
