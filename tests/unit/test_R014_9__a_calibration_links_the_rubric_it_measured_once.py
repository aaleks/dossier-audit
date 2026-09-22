"""R14.9 row 2 — a calibration links the rubric it measured, once per field.

A calibration is a measurement *of* a rubric, so its record is where the link
matters most. Two grounding states measured against one rubric are two judges
and one prompt (R7.22), and a second link to the same version would say
nothing the first did not.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import FakeModelClient, FakePromptRegistry, FakeTracker

from dossier.application.eval import FieldSample, calibrate_fields
from dossier.domain.gold import CalibrationCase
from dossier.domain.grounding import DESCRIBED, GROUNDED, judge_name
from dossier.domain.judges import MINIMUM_SAMPLE
from dossier.domain.ports import ImagePart

FIELD = "root_cause"
RUBRIC = "incident-audit.judge.root_cause"
RUBRIC_HASH = "f7a2d9c4" * 8
DOCUMENT = "INC-4830"


def _sample(state: str) -> FieldSample:
    return FieldSample(
        cases=[
            CalibrationCase(
                document=DOCUMENT,
                answer=f"candidate {index}",
                supported=True,
                verified_by="a.aleks",
                verified_at="2026-09-19",
            )
            for index in range(MINIMUM_SAMPLE)
        ],
        rubric="is it supported?",
        rubric_hash=RUBRIC_HASH,
        field=FIELD,
        state=state,
    )


class TestACalibrationLinksTheRubricItMeasuredOnce:
    """R14.9 — a calibration links the rubric version it measured."""

    def test_two_states_measured_against_one_rubric_link_it_once(self, tmp_path: Path):
        """Row 2: the one with two judges and one prompt."""
        registry, tracker = FakePromptRegistry(), FakeTracker()
        registry.publish(
            name=RUBRIC, template="is it supported?", tags={"dossier.prompt_hash": RUBRIC_HASH}
        )
        samples = {FIELD: _sample(GROUNDED), judge_name(FIELD, DESCRIBED): _sample(DESCRIBED)}
        model = FakeModelClient(
            responses=[json.dumps({"supported": True})] * (2 * MINIMUM_SAMPLE)
        )

        calibrate_fields(
            model,
            directory=tmp_path,
            samples=samples,
            documents={DOCUMENT: "The certificate was never deployed."},
            judge_model="openai:gpt-5.4-mini",
            parts={DOCUMENT: [ImagePart(media_type="image/png", data=b"\x89PNG one")]},
            tracker=tracker,
            pipeline="incident-audit",
            prompt_registry=registry,
        )

        assert tracker.links == [(RUBRIC, 1)]
