"""R7.22 — `dossier calibrate` measures each grounding state against its own sample.

A judge shown pages and a judge shown text are two judges asked two questions.
Measuring one and filing it as the other would put a figure behind a gate it
was never measured for, which is R7.15's failure with better paperwork.

Against a fake that counts calls and records what each was shown: every row is
a claim about which judge was asked with what, and about which file came out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier.application.eval import (
    CALIBRATIONS_DIR,
    SHOWN_AS_PAGES,
    FieldSample,
    calibrate_fields,
)
from dossier.domain.gold import CalibrationCase
from dossier.domain.grounding import DESCRIBED, GROUNDED, judge_name
from dossier.domain.judges import MINIMUM_SAMPLE, NotCalibrated
from dossier.domain.ports import ImagePart

JUDGED = "root_cause"
MODEL = "openai:gpt-5.4-mini"
CHART = "INC-5720-checkout-latency-postmortem.png"

PAGE = ImagePart(media_type="image/png", data=b"\x89PNG\r\n\x1a\n one")
TEXT = "The pool was exhausted by a retry storm after the failover."

SUPPORTED = json.dumps({"supported": True, "evidence": "stated"})


def _cases(count: int = MINIMUM_SAMPLE) -> list[CalibrationCase]:
    """A sample of the minimum size, alternating verdicts."""
    return [
        CalibrationCase(
            document=CHART,
            answer=f"candidate {index}",
            supported=index % 2 == 0,
            verified_by="a.aleks",
            verified_at="2026-09-19",
        )
        for index in range(count)
    ]


def _sample(state: str, *, count: int = MINIMUM_SAMPLE) -> FieldSample:
    return FieldSample(
        cases=_cases(count),
        rubric="is it supported?",
        rubric_hash="r" * 64,
        field=JUDGED,
        state=state,
    )


def _measure(tmp_path: Path, samples, *, responses: int):
    from tests.fakes import FakeModelClient

    model = FakeModelClient(responses=[SUPPORTED] * responses)
    measured = calibrate_fields(
        model,
        directory=tmp_path,
        samples=samples,
        documents={CHART: TEXT},
        judge_model=MODEL,
        parts={CHART: [PAGE]},
    )
    return model, measured


class TestEachGroundingStateIsMeasuredOnItsOwnSample:
    """R7.22 — two judges, two samples, two files."""

    def test_two_states_write_two_calibrations(self, tmp_path: Path):
        """Example 1: the one where both judges are measured and kept apart.

        The grounded name is unchanged, so a gold set written before there were
        two states is read by the same path it always was (R7.20 row 2).
        """
        samples = {
            JUDGED: _sample(GROUNDED),
            judge_name(JUDGED, DESCRIBED): _sample(DESCRIBED),
        }

        _, measured = _measure(tmp_path, samples, responses=2 * MINIMUM_SAMPLE)

        assert set(measured) == {JUDGED, f"{JUDGED}.{DESCRIBED}"}
        assert (tmp_path / CALIBRATIONS_DIR / f"{JUDGED}.json").is_file()
        assert (tmp_path / CALIBRATIONS_DIR / f"{JUDGED}.{DESCRIBED}.json").is_file()
        assert all(m.sample_size == MINIMUM_SAMPLE for m in measured.values())

    def test_the_described_judge_is_shown_pages_and_the_body_eval_asks_with(
        self, tmp_path: Path
    ):
        """Example 2: the one that makes the figure transferable.

        A state measured on a prompt it is not asked with is a figure about
        nothing, and the bar would then be set from it. So the sentence here is
        the sentence R7.21 asks with, and it is the same constant.
        """
        model, _ = _measure(
            tmp_path,
            {judge_name(JUDGED, DESCRIBED): _sample(DESCRIBED)},
            responses=MINIMUM_SAMPLE,
        )

        assert model.call_count == MINIMUM_SAMPLE
        assert all(call["parts"] == (PAGE,) for call in model.calls)
        assert all(SHOWN_AS_PAGES in str(call["prompt"]) for call in model.calls)

    def test_the_grounded_judge_is_still_shown_the_text(self, tmp_path: Path):
        """Example 2's other half: nothing about the text judge moves (R7.11)."""
        model, _ = _measure(tmp_path, {JUDGED: _sample(GROUNDED)}, responses=MINIMUM_SAMPLE)

        assert all(call["parts"] == () for call in model.calls)
        assert all(TEXT in str(call["prompt"]) for call in model.calls)

    def test_a_short_described_sample_is_refused_before_any_call(self, tmp_path: Path):
        """Example 3: the one where nineteen cases buy nothing.

        Refused before a judge is asked, and the state is named -- otherwise
        the reader is told `root_cause` is short while the file they need to
        grow is the other one (R7.14 row 3).
        """
        from tests.fakes import FakeModelClient

        model = FakeModelClient(responses=[])
        name = judge_name(JUDGED, DESCRIBED)

        with pytest.raises(NotCalibrated) as raised:
            calibrate_fields(
                model,
                directory=tmp_path,
                samples={name: _sample(DESCRIBED, count=MINIMUM_SAMPLE - 1)},
                documents={CHART: TEXT},
                judge_model=MODEL,
                parts={CHART: [PAGE]},
            )

        assert name in str(raised.value)
        assert model.call_count == 0
        assert not (tmp_path / CALIBRATIONS_DIR).exists(), "a refused sample left a file"

    def test_a_pipeline_with_one_state_writes_one_calibration(self, tmp_path: Path):
        """Counter-example 5: the one where no described sample is looked for.

        Nothing in a `per_file` pipeline can produce a described verdict, so a
        sample for one would be twenty cases nobody can act on.
        """
        _, measured = _measure(tmp_path, {JUDGED: _sample(GROUNDED)}, responses=MINIMUM_SAMPLE)

        assert set(measured) == {JUDGED}
        assert list((tmp_path / CALIBRATIONS_DIR).iterdir()) == [
            tmp_path / CALIBRATIONS_DIR / f"{JUDGED}.json"
        ]
