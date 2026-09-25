"""R7.29 — `dossier calibrate` prints, writes and records the same lower bound,
kappa and counts.

R7.26 – R7.28 decide the figures. This is where they go: one more terminal line
under each judge's agreement line, the calibration file beside the agreement,
and the calibrate run's metrics and description -- the three places the
agreement already goes, so that none of them can say something the others do
not (spec 011). What the command prints is proved beside this file, in the
acceptance test; what each place is given is decided here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, FakeTracker

from dossier.domain.gold import CalibrationCase
from dossier.domain.judges import Calibration, Tally, calibration, withholding
from dossier.domain.tracking import calibration_record, judge_line, statistics_line

MODEL = "openai:gpt-5.4-mini"
RUBRIC = "Is the stated root cause supported by the named document?\n"
RUBRIC_HASH = "f7a2d9c4"
PROMPT_HASH = "0443845a"


def _human(supported: int = 12) -> dict[str, bool]:
    """R7.11's sample: twenty cases, the first `supported` of them marked supported."""
    return {f"rc-{index:02d}": index < supported for index in range(20)}


def _measured(verdicts: dict[str, bool], human: dict[str, bool]) -> Calibration:
    return calibration(
        verdicts=verdicts,
        human=human,
        judge_model=MODEL,
        rubric_hash=RUBRIC_HASH,
        prompt_hash=PROMPT_HASH,
    )


def _cases(verdicts: list[bool]) -> list[CalibrationCase]:
    return [
        CalibrationCase(
            document=f"INC-{4800 + index}",
            answer=f"candidate answer {index}",
            supported=supported,
            verified_by="a.aleks",
            verified_at="2026-09-15",
        )
        for index, supported in enumerate(verdicts)
    ]


class TestCalibratePrintsWritesAndRecordsTheSameFigures:
    """R7.29 — the figures go everywhere the agreement already goes."""

    def test_the_terminal_line_says_what_the_agreement_hides(self):
        """Row 1: the one where the three places agree, as the terminal shows it.

        Under the agreement line, starting where its percentage starts, so the
        eye reads down one column of figures.
        """
        human = _human()
        measured = _measured(dict(human), human)
        above = judge_line(field="root_cause", agreement=1.0, cases=20, judge_model=MODEL)

        line = statistics_line(measured)

        assert line == (
            " " * 19
            + "lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8"
        )
        assert line.index("lower") == above.index("100.0%")

    def test_the_calibration_file_holds_the_figures(self):
        """Row 2, the file: beside the agreement, as the file is written (R7.14)."""
        human = _human()

        written = _measured(dict(human), human).model_dump()

        assert written["lower_bound"] == pytest.approx(0.838874842, abs=1e-9)
        assert written["kappa"] == 1.0
        assert written["supported"] == {"agreed": 12, "cases": 12}
        assert written["unsupported"] == {"agreed": 8, "cases": 8}

    def test_the_run_records_the_figures_rounded_as_the_terminal_prints_them(self):
        """Row 2, the run: percentages to the one decimal printed, kappa to two (R11.5)."""
        human = _human()

        _, metrics = calibration_record(
            field="root_cause", calibration=_measured(dict(human), human)
        )

        assert metrics == {
            "judge/root_cause/agreement": 100.0,
            "judge/root_cause/cases": 20,
            "judge/root_cause/lower_bound": 83.9,
            "judge/root_cause/kappa": 1.0,
            "judge/root_cause/supported": 100.0,
            "judge/root_cause/unsupported": 100.0,
        }

    def test_a_measurement_writes_and_records_what_it_prints(self, tmp_path: Path):
        """Rows 1 and 2 at the measurement: the file, the metrics and the description.

        One unsupported claim let through, so no figure is a round one that a
        default could produce by accident.
        """
        from dossier.application.eval import FieldSample, calibrate_fields

        cases = _cases([True] * 12 + [False] * 8)
        replies = [json.dumps({"supported": case.supported}) for case in cases]
        replies[19] = json.dumps({"supported": True})
        tracker = FakeTracker()

        measured = calibrate_fields(
            FakeModelClient(responses=replies),
            directory=tmp_path,
            samples={
                "root_cause": FieldSample(cases=cases, rubric=RUBRIC, rubric_hash=RUBRIC_HASH)
            },
            documents={case.document: f"The text of {case.document}." for case in cases},
            judge_model=MODEL,
            tracker=tracker,
            experiment="dossier-audit/incident-audit/calibrate",
            pipeline="incident-audit",
        )

        line = statistics_line(measured["root_cause"])
        assert line.strip() == (
            "lower bound 76.4% · kappa 0.89 · supported 12 of 12 · unsupported 7 of 8"
        )
        written = json.loads(
            (tmp_path / "calibrations" / "root_cause.json").read_text(encoding="utf-8")
        )
        assert written["supported"] == {"agreed": 12, "cases": 12}
        assert written["unsupported"] == {"agreed": 7, "cases": 8}
        (run,) = tracker.runs
        assert run.metrics["judge/root_cause/lower_bound"] == 76.4
        assert run.metrics["judge/root_cause/kappa"] == 0.89
        assert run.metrics["judge/root_cause/unsupported"] == 87.5
        assert line.strip() in run.tags["mlflow.note.content"].splitlines()

    def test_each_grounding_state_records_under_its_own_name(self):
        """Row 3: the one where each grounding state has its own figures (R7.22)."""
        human = _human()

        _, metrics = calibration_record(
            field="root_cause.described", calibration=_measured(dict(human), human)
        )

        assert metrics["judge/root_cause.described/lower_bound"] == 83.9
        assert metrics["judge/root_cause.described/unsupported"] == 100.0

    def test_a_figure_that_is_not_measurable_is_said_and_never_sent(self):
        """Row 4: the one where a figure is not measurable.

        A reviewer who marked all twenty supported leaves kappa nothing to
        measure and the unsupported half nothing to count. The file says so with
        `null` and a zero count, the terminal in words, and MLflow by holding no
        metric: it has no null, and a 0 would be charted as a judge that scored 0.
        """
        human = _human(supported=20)
        measured = _measured(dict(human), human)

        written = measured.model_dump()
        _, metrics = calibration_record(field="root_cause", calibration=measured)

        assert written["kappa"] is None
        assert written["unsupported"] == {"agreed": 0, "cases": 0}
        assert statistics_line(measured).strip() == (
            "lower bound 83.9% · kappa not measurable · supported 20 of 20 · "
            "no unsupported case"
        )
        assert "judge/root_cause/kappa" not in metrics
        assert "judge/root_cause/unsupported" not in metrics
        assert metrics["judge/root_cause/supported"] == 100.0

    def test_a_calibration_written_before_these_figures_gates_as_before(self):
        """Row 5, counter-example: the one where an old calibration still gates as before.

        Every new figure is optional, so the file loads; the gate reads the
        agreement (R7.5); and the record holds only what the file holds, with no
        figure invented for a measurement that never took it.
        """
        old = Calibration.model_validate(
            {
                "judge_model": MODEL,
                "rubric_hash": RUBRIC_HASH,
                "prompt_hash": PROMPT_HASH,
                "agreement": 1.0,
                "sample_size": 20,
            }
        )

        assert (old.lower_bound, old.kappa, old.supported, old.unsupported) == (
            None,
            None,
            None,
            None,
        )
        assert (
            withholding(
                old,
                judge_model=MODEL,
                rubric_hash=RUBRIC_HASH,
                prompt_hash=PROMPT_HASH,
                threshold=0.95,
            )
            is None
        )
        _, metrics = calibration_record(field="root_cause", calibration=old)
        assert metrics == {"judge/root_cause/agreement": 100.0, "judge/root_cause/cases": 20}
        assert statistics_line(old) is None

    def test_the_counts_the_file_holds_are_tallies(self):
        """The file's halves read back as the tallies they were written from."""
        human = _human()
        measured = _measured(dict(human), human)

        again = Calibration.model_validate_json(measured.model_dump_json())

        assert again == measured
        assert again.unsupported == Tally(agreed=8, cases=8)
