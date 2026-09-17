"""R7.14 — `dossier calibrate` measures a judge against the gold set's sample and
writes the calibration beside it.

The measurement itself is R7.11's; this rule is where the figure is *kept*, and
why it is kept apart from the bar it is judged against. A calibration is
measured; a threshold is agreed by a person (R7.13). A run able to rewrite its
own bar would not be gated by it.

The application half is here: given a judge, a sample and the documents' text, it
measures and writes `<gold>/calibrations/<field>.json`. Where the CLI gets that
text is the acceptance test beside this one -- the command converts what the
workspace holds, as `dossier convert` does.

Row 4 of the rule -- a judged field with no sample at all -- is
`load_calibration_sample`'s refusal. It was once described here as proved under
R7.16, and R7.16's rows are about a record's shape and never open a missing
file; `/verify` found the `except` could be deleted with the suite green. So it
is transcribed here after all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient

from dossier.application.eval import judge_prompt_hash
from dossier.domain.gold import CalibrationCase
from dossier.domain.judges import MINIMUM_SAMPLE, NotCalibrated

FIELD = "root_cause"
JUDGE = "openai:gpt-5.4-mini"
RUBRIC = "Is the stated root cause supported by the named document?\n"
RUBRIC_HASH = "0e52dd18" * 8

# Twelve supported and eight not, the way the sample R7.11 measured is split. A
# judge that agreed with everything would score 60% on this shape, which is the
# floor any figure has to clear to mean anything.
VERDICTS = [True] * 12 + [False] * 8


def _cases(count: int = len(VERDICTS)) -> list[CalibrationCase]:
    return [
        CalibrationCase(
            document=f"INC-{4800 + index}",
            answer=f"candidate answer {index}",
            supported=supported,
            verified_by="a.aleks",
            verified_at="2026-09-15",
        )
        for index, supported in enumerate(VERDICTS[:count])
    ]


def _documents(cases: list[CalibrationCase]) -> dict[str, str]:
    return {case.document: f"The text of {case.document}." for case in cases}


def _replies(cases: list[CalibrationCase], *, disagree_at: int | None = None) -> list[str]:
    """What the judge answers, case by case: the reviewer's verdict, or its opposite."""
    return [
        json.dumps(
            {"supported": case.supported if index != disagree_at else not case.supported}
        )
        for index, case in enumerate(cases)
    ]


def _calibrate(
    model, directory: Path, cases: list[CalibrationCase], *, judge_model: str = JUDGE
):
    """The measurement, run the way `dossier calibrate` will run it.

    Imported inside the helper rather than at module scope: until this lands,
    collecting the default suite would error on a name that does not exist yet,
    and a red collection is not the same as a red test.
    """
    from dossier.application.eval import calibrate_field

    return calibrate_field(
        model,
        directory=directory,
        field=FIELD,
        cases=cases,
        rubric=RUBRIC,
        rubric_hash=RUBRIC_HASH,
        documents=_documents(cases),
        judge_model=judge_model,
    )


def _written(directory: Path) -> dict:
    path = directory / "calibrations" / f"{FIELD}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestCalibrateWritesWhatItMeasured:
    """R7.14 — the figure, with the judge and the rubric it was measured against."""

    def test_a_measured_judge_is_written_beside_the_gold_set(self, tmp_path: Path):
        """Example 1: the one over a full sample, with a single disagreement.

        Nineteen of twenty, so 0.95 -- and the file carries the judge and the
        rubric as well as the number, because an agreement figure on its own says
        a judge agreed with a human without saying which judge or on what
        question (R7.11 row 2).

        One judge call per case is asserted, not assumed. A measurement that
        skipped a case would still produce a percentage, and it would be a
        percentage of something else.
        """
        cases = _cases()
        model = FakeModelClient(responses=_replies(cases, disagree_at=7))

        measured = _calibrate(model, tmp_path, cases)

        assert model.call_count == len(cases)
        assert measured.agreement == 0.95
        assert measured.sample_size == 20
        assert _written(tmp_path) == {
            "judge_model": JUDGE,
            "rubric_hash": RUBRIC_HASH,
            "prompt_hash": judge_prompt_hash(),
            "agreement": 0.95,
            "sample_size": 20,
        }

    def test_a_new_measurement_replaces_the_old(self, tmp_path: Path):
        """Example 2: the one where the judge changed since the last run.

        The file records what is true now. Keeping the old figure beside it would
        leave two answers to "what did this judge score", and R7.6 is what notices
        that a calibration belongs to a judge nobody is using any more.
        """
        cases = _cases()
        _calibrate(
            FakeModelClient(responses=_replies(cases)), tmp_path, cases, judge_model=JUDGE
        )

        _calibrate(
            FakeModelClient(responses=_replies(cases, disagree_at=3)),
            tmp_path,
            cases,
            judge_model="anthropic:claude-haiku-4-5-20251001",
        )

        written = _written(tmp_path)
        assert written["judge_model"] == "anthropic:claude-haiku-4-5-20251001"
        assert written["agreement"] == 0.95

    def test_a_sample_below_the_minimum_is_refused_naming_the_count(self, tmp_path: Path):
        """Example 3: the one measured on nineteen cases.

        Not measurable at this N, never rounded into a percentage (R7.11 row 3).
        And nothing is written: a file that existed would be read back as a
        calibration, and "refused" would have produced one anyway.
        """
        cases = _cases(MINIMUM_SAMPLE - 1)
        model = FakeModelClient(responses=_replies(cases))

        with pytest.raises(NotCalibrated) as error:
            _calibrate(model, tmp_path, cases)

        assert "19" in str(error.value)
        assert not (tmp_path / "calibrations").exists()

    def test_a_field_with_no_sample_is_refused_naming_the_field_and_the_path(
        self, tmp_path: Path
    ):
        """Example 4: the one where nobody has written `samples/root_cause.jsonl`.

        Refused, and the message says where the file was looked for, because
        that is where the fix goes. A judge cannot be measured against a sample
        nobody has written, and a measurement that proceeded over nothing would
        leave a calibration file behind for it.
        """
        from dossier.config.load import ConfigError, load_calibration_sample

        with pytest.raises(ConfigError) as error:
            load_calibration_sample(tmp_path, FIELD)

        assert FIELD in str(error.value)
        assert str(tmp_path / "samples" / f"{FIELD}.jsonl") in str(error.value)
        assert not (tmp_path / "calibrations").exists()

    def test_the_agreed_threshold_is_neither_written_nor_read(self, tmp_path: Path):
        """Counter-example (row 5): `judge.yaml` is untouched by a measurement.

        The bar is agreed by a person and the figure is measured by a machine.
        A calibration run that could move the bar it is judged against would be
        a judge grading its own paper (R7.13).
        """
        bar = tmp_path / "judge.yaml"
        bar.write_text(f"{FIELD}: 0.95\n", encoding="utf-8")
        before = bar.read_bytes()
        cases = _cases()

        _calibrate(FakeModelClient(responses=_replies(cases)), tmp_path, cases)

        assert bar.read_bytes() == before
