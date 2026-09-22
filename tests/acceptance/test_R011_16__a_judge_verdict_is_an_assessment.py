"""R11.16 — a judge's verdict is an assessment on the trace the eval already opened.

An eval opens one trace per judged (field, document) (R7.18 row 5). MLflow's
Evaluations view reads assessments on traces, and dossier attached none, so the
view was empty for the one part of scoring that is not arithmetic.

Recorded, never computed. `mlflow.genai.evaluate` would have MLflow arrive at a
verdict of its own from the same material, which is the second-way-of-computing
spec 011 forbids; an assessment is a projection of a verdict dossier already
reached, one way only, as a published dataset is (R12.4).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeTracker
from tests.scoring_example import PIPELINE, RoutedModel

EVIDENCE = "the paragraph stating the certificate was never deployed"


class JudgingModel(RoutedModel):
    """The scoring example's answers, and a verdict for whatever the judge asks."""

    supported = True

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        if "<claim>" in prompt:
            self.calls.append("judge")
            return json.dumps({"supported": self.supported, "evidence": EVIDENCE})
        return super().complete(prompt, schema=schema, parts=parts)


@pytest.fixture
def judge(monkeypatch) -> JudgingModel:
    import dossier.cli.main as cli

    model = JudgingModel({})
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return model


@pytest.fixture
def tracker(judge: JudgingModel, monkeypatch) -> FakeTracker:
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


def _assessments(recorder: FakeTracker) -> list[dict]:
    return [found for trace in recorder.traces for found in trace.assessments]


class TestAJudgeVerdictIsAnAssessment:
    """R11.16 — a judge's verdict is an assessment on the trace already opened."""

    def test_a_supported_verdict_is_an_assessment_named_for_its_field(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one that fills MLflow's Evaluations view.

        Named for the field, valued with the verdict, carrying the evidence the
        judge gave and sourced to the model that gave it -- so a verdict can be
        read back without opening a cache entry on the machine that scored.
        """
        workspace, _ = judged_run

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        found = _assessments(tracker)
        assert found, "a judged verdict is an assessment"
        assert found[0]["name"] == "root_cause"
        assert found[0]["value"] is True
        assert found[0]["rationale"] == EVIDENCE
        assert found[0]["source"] == RoutedModel.model_id

    def test_an_unsupported_verdict_is_recorded_as_one(
        self, judged_run: tuple[Path, str], monkeypatch, judge: JudgingModel, tracker
    ):
        """Example 2: the one that tells a working judge from one agreeing with everything.

        R7.12's planted claim is the case this makes filterable. A view holding
        only the verdicts that passed would be the most misleading possible
        summary of a judge.
        """
        workspace, _ = judged_run
        judge.supported = False

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert _assessments(tracker)[0]["value"] is False

    def test_a_verdict_served_from_cache_is_still_an_assessment(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 3: the one that separates what was recorded from what it cost.

        The second eval asks nothing (R7.18), and it scored the same verdict. An
        assessment appearing only on a cache miss would make a second eval of one
        run look like it judged nothing -- which is exactly the run a person
        opens when they want to read the verdicts at leisure.
        """
        workspace, _ = judged_run
        first = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
        assert first.exit_code == 0, first.output

        second = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert second.exit_code == 0, second.output
        recorded = [found for trace in tracker.runs[1].traces for found in trace.assessments]
        assert recorded, "the verdict was scored, so it is on the record"
        assert recorded[0]["value"] is True
        assert not [span for trace in tracker.runs[1].traces for span in trace.spans], (
            "and it cost no call"
        )

    def test_hashes_capture_records_the_verdict_and_not_the_evidence(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 4: the one where the document may not reach the server.

        The evidence quotes the document, so it obeys the same setting the span
        does (R10.8). The verdict is not a quotation and is recorded either way,
        which is what keeps the view usable on a machine that withholds text.
        """
        workspace, _ = judged_run
        monkeypatch.setenv("DOSSIER_MLFLOW_CAPTURE", "hashes")

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        found = _assessments(tracker)
        assert found[0]["value"] is True
        assert found[0]["rationale"] == ""

    def test_nothing_is_assessed_for_a_field_that_was_never_judged(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 5): the one whose judge may not be quoted (R7.15).

        A withheld field is not judged at all, so there is nothing to project.
        Nothing is measured for a number nobody may print (R7.17).
        """
        workspace, _ = judged_run
        (workspace / "gold" / "incidents" / "calibrations" / "root_cause.json").unlink()

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert _assessments(tracker) == []
