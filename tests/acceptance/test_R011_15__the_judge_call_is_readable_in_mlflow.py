"""R11.15 — the judge's LLM span carries what a stage span carries.

The unit test beside this one proves what the payload holds. This one proves an
eval puts it on the span it already opens -- and that a verdict served from the
cache still opens no span at all, which is R7.18's claim seen from the other
side: seeing that a verdict cost nothing is information.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeTracker
from tests.scoring_example import PIPELINE, RoutedModel


class JudgingModel(RoutedModel):
    """The scoring example's answers, plus a verdict for anything the judge asks."""

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        if "<claim>" in prompt:
            self.calls.append("judge")
            return json.dumps(
                {"supported": True, "evidence": "the paragraph naming the batch host"}
            )
        return super().complete(prompt, schema=schema, parts=parts)


@pytest.fixture
def tracker(monkeypatch) -> FakeTracker:
    import dossier.cli.bootstrap as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: JudgingModel({}))
    return recorder


def _llm_spans(recorder: FakeTracker) -> list[dict]:
    return [span for span in recorder.spans if span["kind"] == "llm"]


class TestTheJudgeCallIsReadableInMLflow:
    """R11.15 — the judge's LLM span carries what a stage span carries."""

    def test_the_span_holds_the_question_and_the_reply_under_full_capture(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where the judge's reasoning becomes readable.

        The span held `dossier.model` and nothing else. The verdict and the
        evidence were in a cache entry on the scoring machine, so a person
        reading MLflow could see that a judge had been asked and never what it
        said.
        """
        workspace, _ = judged_run

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        spans = _llm_spans(tracker)
        assert spans, "the judge was asked, so there is a span"
        assert "<claim>" in spans[0]["prompt"]
        assert "supported" in spans[0]["reply"]
        assert spans[0]["dossier.field"] == "root_cause"

    def test_hashes_capture_puts_no_document_text_on_the_span(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where the document may not reach the server.

        A judge's question embeds the whole document and the candidate answer,
        so this setting has more to withhold here than anywhere else (R10.8).
        """
        workspace, _ = judged_run
        monkeypatch.setenv("DOSSIER_MLFLOW_CAPTURE", "hashes")

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        spans = _llm_spans(tracker)
        assert spans, "the judge was asked, so there is a span"
        assert "prompt" not in spans[0]
        assert "reply" not in spans[0]
        assert spans[0]["key"], "a hash stands in for each of them"
        assert spans[0]["dossier.field"] == "root_cause"

    def test_a_verdict_served_from_cache_opens_no_llm_span_at_all(
        self, judged_run: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 4): the one where the verdict was free.

        R7.18 already has it: the judge is asked only on a miss. A second eval of
        one run asks nothing, so there is nothing to carry -- and the trace is
        still there, which is how a person sees that it cost nothing.
        """
        workspace, _ = judged_run
        first = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
        assert first.exit_code == 0, first.output
        assert _llm_spans(tracker), "the first eval asked"

        second = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert second.exit_code == 0, second.output
        assert tracker.runs[1].traces, "the verdicts were still traced"
        assert not [span for trace in tracker.runs[1].traces for span in trace.spans], (
            "and none of them cost a call"
        )
