"""R11.5 — a `dossier calibrate` is one MLflow run per gold set holding what it
measured, with one trace per sample case. The CLI half.

The unit test beside this one proves what a calibration *records*. This one
proves the command *makes* the record -- the rule's Given -- because R11.3 and
R11.4 were both MET one layer below the command they named, and neither worked.

What the run adds to the file R7.14 writes is what the file cannot hold: every
measurement rather than the latest, and the case-by-case verdicts behind the
agreement figure. What it leaves out is the bar: a calibration never reads
`judge.yaml` (R7.14 row 5), and the run that records both the figure and whether
it cleared the bar is the eval's (R11.3 row 4).

The judge is a `FakeModelClient` and the tracker a `FakeTracker`, both handed to
the CLI through the seams every other acceptance test uses. Tracking is switched
on after the sync, so the one MLflow run under test is the calibration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

from dossier.domain.hashing import text_hash

pytestmark = pytest.mark.outer_loop

FIELD = "root_cause"
GOLD = "gold/incidents"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
OTHER_JUDGE = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
URI = "http://localhost:5000"

# Twenty cases over the four documents the source holds, twelve supported to
# eight, as the sample R7.11 measured is.
VERDICTS = [True] * 12 + [False] * 8


def _cases() -> list[dict]:
    keys = sorted(ISSUES)
    return [
        {
            "document": keys[index % len(keys)],
            "answer": f"candidate answer {index}",
            "supported": supported,
            "verified_by": "a.aleks",
            "verified_at": "2026-09-15",
        }
        for index, supported in enumerate(VERDICTS)
    ]


def _replies(cases: list[dict], *, disagree_at: int | None = None) -> list[str]:
    """What the judge answers, case by case: the reviewer's verdict, or its opposite."""
    return [
        json.dumps(
            {"supported": case["supported"] if index != disagree_at else not case["supported"]}
        )
        for index, case in enumerate(cases)
    ]


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _verdict(supported: bool) -> str:
    return "supported" if supported else "unsupported"


@pytest.fixture
def calibratable(workspace: Path, monkeypatch) -> Path:
    """A synced workspace whose gold set carries a bar and a twenty-case sample."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    path = write_pipeline(workspace, sources=[SOURCE_ID])
    path.write_text(path.read_text(encoding="utf-8") + f"gold: {GOLD}/\n", encoding="utf-8")
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )

    gold = workspace / "gold" / "incidents"
    (gold / "samples").mkdir(parents=True)
    (gold / "judge.yaml").write_text(f"{FIELD}: 0.95\n", encoding="utf-8")
    (gold / "samples" / f"{FIELD}.jsonl").write_text(
        "\n".join(json.dumps(case) for case in _cases()) + "\n", encoding="utf-8"
    )

    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


@pytest.fixture
def tracker(calibratable: Path, monkeypatch) -> FakeTracker:
    """Tracking switched on after the sync, recording to a fake that counts."""
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


def _judge(monkeypatch, replies: list[str]) -> FakeModelClient:
    import dossier.cli.main as cli

    judge = FakeModelClient(responses=replies)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)
    return judge


class TestCalibrateRecordsToMLflow:
    """R11.5 — a calibration is one MLflow run, with one trace per sample case."""

    def test_a_calibration_is_one_run_holding_the_figures_the_file_holds(
        self, calibratable: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where the measurement lands as one run.

        The agreement is the percentage the terminal prints, as accuracy is
        (spec 011), and the model and rubric hash travel with it for the reason
        R7.14 gives: a figure measured against another judge is not this one's.
        """
        _judge(monkeypatch, _replies(_cases()))

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1, "one calibration is one MLflow run"
        run = tracker.runs[0]
        assert run.experiment == f"dossier-audit/{PIPELINE}/calibrate"
        assert run.tags["dossier.kind"] == "calibrate"
        assert run.tags["dossier.pipeline"] == PIPELINE
        assert re.fullmatch(r"[0-9a-f]{64}", run.tags["dossier.gold_hash"])
        rubric = calibratable / "pipelines" / PIPELINE / "rubrics" / f"{FIELD}.md"
        assert run.params[f"judge/{FIELD}/model"] == MODEL
        assert run.params[f"judge/{FIELD}/rubric"] == text_hash(rubric)
        assert run.metrics == {f"judge/{FIELD}/agreement": 100.0, f"judge/{FIELD}/cases": 20.0}

    def test_each_case_is_a_trace_carrying_both_verdicts_and_one_llm_span(
        self, calibratable: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where the disagreeing case can be found.

        Twenty cases, twenty traces, each tagged with the document, the verdict
        the reviewer gave and the one the judge gave. Case 7 is where they
        differ, and finding it is a filter on two tags rather than a re-run.
        Each trace holds exactly one LLM span, so the trace count and the
        judge's call count are the same claim seen twice (R11.2).
        """
        cases = _cases()
        judge = _judge(monkeypatch, _replies(cases, disagree_at=7))

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        traces = tracker.runs[0].traces
        assert len(traces) == 20 == judge.call_count
        assert [trace.tags["dossier.document"] for trace in traces] == [
            case["document"] for case in cases
        ]
        assert [trace.tags["dossier.verified"] for trace in traces] == [
            _verdict(case["supported"]) for case in cases
        ]
        disagreeing = [
            index
            for index, trace in enumerate(traces)
            if trace.tags["dossier.judged"] != trace.tags["dossier.verified"]
        ]
        assert disagreeing == [7]
        assert all(
            len([span for span in trace.spans if span["kind"] == "llm"]) == 1
            for trace in traces
        ), "one judge call per case is one LLM span per trace"

    def test_a_second_measurement_is_a_second_run_beside_the_first(
        self, calibratable: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 3: the one where a rejected judge still leaves a record.

        The file holds only the latest measurement (R7.14 row 2). The experiment
        holds both, each with its own model param and agreement -- which is the
        whole reason a calibration records at all.
        """
        cases = _cases()
        _judge(monkeypatch, _replies(cases))
        first = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)
        assert first.exit_code == 0, first.output

        pipeline = calibratable / "pipelines" / PIPELINE / "pipeline.yaml"
        pipeline.write_text(
            pipeline.read_text(encoding="utf-8").replace(MODEL, OTHER_JUDGE), encoding="utf-8"
        )
        _judge(monkeypatch, _replies(cases, disagree_at=7))
        second = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert second.exit_code == 0, second.output
        assert len(tracker.runs) == 2, "a re-measure is a second run, not a rewrite"
        assert [run.experiment for run in tracker.runs] == [
            f"dossier-audit/{PIPELINE}/calibrate"
        ] * 2
        assert [run.params[f"judge/{FIELD}/model"] for run in tracker.runs] == [
            MODEL,
            OTHER_JUDGE,
        ]
        assert [run.metrics[f"judge/{FIELD}/agreement"] for run in tracker.runs] == [
            100.0,
            95.0,
        ]

    def test_a_refused_calibration_records_nothing(
        self, calibratable: Path, monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 4): the one where nothing was measured.

        Nineteen cases is refused before the first judge call (R7.14 row 3), and
        a run recorded for it would read back as a measurement that happened.
        """
        short = _cases()[:-1]
        (calibratable / "gold" / "incidents" / "samples" / f"{FIELD}.jsonl").write_text(
            "\n".join(json.dumps(case) for case in short) + "\n", encoding="utf-8"
        )
        judge = _judge(monkeypatch, _replies(short))

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code != 0
        assert judge.call_count == 0
        assert tracker.runs == [], "0 MLflow runs, 0 traces"

    def test_the_bar_is_not_on_the_run(
        self, calibratable: Path, monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 5): the one where the bar stays out of the measurement.

        `judge.yaml` declares 0.95, and nothing on the run says so. A calibration
        never reads the bar (R7.14 row 5), and a run that carried it beside the
        agreement would read as having applied it.
        """
        _judge(monkeypatch, _replies(_cases()))

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        run = tracker.runs[0]
        recorded = {**run.tags, **run.params, **{k: str(v) for k, v in run.metrics.items()}}
        assert not any("threshold" in key or "judge.yaml" in key for key in recorded)
        assert "0.95" not in recorded.values()
