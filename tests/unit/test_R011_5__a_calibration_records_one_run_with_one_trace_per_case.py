"""R11.5 — a `dossier calibrate` is one MLflow run per gold set holding what it
measured, with one trace per sample case.

The figures are the ones R7.14 writes to `calibrations/<field>.json` and the
terminal prints, so the file, the terminal and MLflow cannot disagree (spec
011). The decision of what a calibration records, and under which names, is
pure; recording it is the tracker port's, and the acceptance test beside this
one proves the command does.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import FakeModelClient, FakeTracker

from dossier.domain.gold import CalibrationCase, gold_set_hash
from dossier.domain.judges import Calibration

MODEL = "anthropic:claude-sonnet-4-5-20250929"
RUBRIC = "Is the stated root cause supported by the named document?\n"
RUBRIC_HASH = "f7a2d9c4" * 8

# Twelve supported and eight not, the way the sample R7.11 measured is split.
VERDICTS = [True] * 12 + [False] * 8


def _cases() -> list[CalibrationCase]:
    return [
        CalibrationCase(
            document=f"INC-{4800 + index}",
            answer=f"candidate answer {index}",
            supported=supported,
            verified_by="a.aleks",
            verified_at="2026-09-15",
        )
        for index, supported in enumerate(VERDICTS)
    ]


def _replies(cases: list[CalibrationCase], *, disagree_at: int | None = None) -> list[str]:
    """What the judge answers, case by case: the reviewer's verdict, or its opposite."""
    return [
        json.dumps(
            {"supported": case.supported if index != disagree_at else not case.supported}
        )
        for index, case in enumerate(cases)
    ]


def _started() -> FakeTracker:
    """A tracker with a run open, as the command opens one before measuring."""
    tracker = FakeTracker()
    tracker.start_run(experiment="dossier-audit/incident-audit/calibrate", name="", tags={})
    return tracker


def _record(calibration: Calibration, *, field: str = "root_cause"):
    """The params and metrics a calibration records for one judged field.

    Imported inside the helper: until this lands, collecting the default suite
    would error on a name that does not exist yet, and a red collection is not
    the same as a red test.
    """
    from dossier.domain.tracking import calibration_record

    return calibration_record(field=field, calibration=calibration)


class TestACalibrationRecordsOneRunWithOneTracePerCase:
    """R11.5 — the run holds what the file holds, under names MLflow can group."""

    def test_the_run_holds_the_figures_the_file_holds(self):
        """Example 1: the one where twenty of twenty is recorded as 100.0 over 20 cases.

        The model and the rubric hash are params -- what the figure was measured
        against -- and the agreement and the case count are metrics, so two runs
        under two judges sit side by side in MLflow's comparison. The agreement
        is the percentage the terminal prints, as accuracy is (spec 011).
        """
        measured = Calibration(
            judge_model=MODEL, rubric_hash=RUBRIC_HASH, agreement=1.0, sample_size=20
        )

        params, metrics = _record(measured)

        assert params == {
            "judge/root_cause/model": MODEL,
            "judge/root_cause/rubric": RUBRIC_HASH,
        }
        assert metrics == {"judge/root_cause/agreement": 100.0, "judge/root_cause/cases": 20}

    def test_a_case_trace_carries_the_document_and_both_verdicts(self):
        """Example 2: the one where the disagreeing case can be found.

        `INC-4830` is the planted case (R7.12): the reviewer marked its
        candidate unsupported, and here the judge marked it supported. Both
        verdicts are tags, so the cases the two disagree on are a filter on the
        experiment rather than a re-run.
        """
        from dossier.domain.tracking import case_tags

        assert case_tags(document="INC-4830", verified=False, judged=True) == {
            "dossier.document": "INC-4830",
            "dossier.verified": "unsupported",
            "dossier.judged": "supported",
        }

    def test_each_case_is_a_trace_with_one_llm_span(self, tmp_path: Path):
        """Example 2, at the measurement: twenty cases, twenty traces, one span each.

        Case 7 is where the judge disagrees, and its trace says so in its tags.
        The trace count and the judge's call count are the same claim seen
        twice (R11.2): a measurement that skipped a case would still produce a
        percentage, and it would be a percentage of something else.
        """
        from dossier.application.eval import calibrate_field

        cases = _cases()
        judge = FakeModelClient(responses=_replies(cases, disagree_at=7))
        tracker = _started()

        calibrate_field(
            judge,
            directory=tmp_path,
            field="root_cause",
            cases=cases,
            rubric=RUBRIC,
            rubric_hash=RUBRIC_HASH,
            documents={case.document: f"The text of {case.document}." for case in cases},
            judge_model=MODEL,
            tracker=tracker,
        )

        traces = tracker.runs[0].traces
        assert len(traces) == 20 == judge.call_count
        assert [trace.tags["dossier.document"] for trace in traces] == [
            case.document for case in cases
        ]
        assert traces[7].tags == {
            "dossier.document": "INC-4807",
            "dossier.verified": "supported",
            "dossier.judged": "unsupported",
        }
        assert all(trace.status == "OK" for trace in traces)
        assert [span["kind"] for trace in traces for span in trace.spans] == ["llm"] * 20

    def test_a_calibration_is_one_run_per_gold_set_holding_every_field(self, tmp_path: Path):
        """Example 1, at the measurement: one run, tagged, holding the figures.

        The run is opened around the whole measurement so every field's traces
        land inside it, and it is tagged with the gold set's hash (R0.7), as an
        eval's is (R11.3 row 2): two calibrations against samples that differ
        by one verdict are not comparable.
        """
        from dossier.application.eval import FieldSample, calibrate_fields

        cases = _cases()
        judge = FakeModelClient(responses=_replies(cases, disagree_at=7))
        tracker = FakeTracker()
        gold_files = {"INC-4821.json": b"{}"}

        measured = calibrate_fields(
            judge,
            directory=tmp_path,
            samples={
                "root_cause": FieldSample(cases=cases, rubric=RUBRIC, rubric_hash=RUBRIC_HASH)
            },
            documents={case.document: f"The text of {case.document}." for case in cases},
            judge_model=MODEL,
            tracker=tracker,
            experiment="dossier-audit/incident-audit/calibrate",
            pipeline="incident-audit",
            gold_files=gold_files,
        )

        assert measured["root_cause"].agreement == 0.95
        assert len(tracker.runs) == 1, "one calibration is one MLflow run"
        run = tracker.runs[0]
        assert run.experiment == "dossier-audit/incident-audit/calibrate"
        assert run.tags["dossier.kind"] == "calibrate"
        assert run.tags["dossier.pipeline"] == "incident-audit"
        assert run.tags["dossier.gold_hash"] == gold_set_hash(gold_files)
        assert run.params == {
            "judge/root_cause/model": MODEL,
            "judge/root_cause/rubric": RUBRIC_HASH,
        }
        assert run.metrics == {"judge/root_cause/agreement": 95.0, "judge/root_cause/cases": 20}
        assert len(run.traces) == 20
        assert run.status == "FINISHED"
