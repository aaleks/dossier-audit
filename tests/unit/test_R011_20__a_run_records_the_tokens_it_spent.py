"""R11.20 — a run's record holds the tokens it spent, and each LLM span carries
its call's tokens where MLflow reads them.

`execute` is run directly with a `FakeTracker` recording what it is told, over
three of the scoring example's incidents, with replies that say what they cost
as a provider's would (R9.18). The metrics are the sums R5.12 prints, handed
over rather than recomputed; the span attribute is MLflow's own key, which
MLflow 3 adds up into the trace's `mlflow.trace.tokenUsage`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient, FakeTracker, NoModelClient
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.run import RunInputs, RunRecording, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import Reply

MODEL = "anthropic:claude-sonnet-4-5-20250929"
RUN_ID = "20260806T142203Z-4f1a"
SECOND_RUN = "20260907T090000Z-bbbb"
USAGE = "mlflow.chat.tokenUsage"
SNAPSHOTS = {
    "INC-4821": "a3f9c1e2" * 8,
    "INC-4822": "77c1b40a" * 8,
    "INC-4901": "0e52dd18" * 8,
}
CONFIG = PipelineConfig(
    name="incident-audit",
    sources=["incidents-jira"],
    model=MODEL,
    steps=[
        StepConfig(
            id="extract",
            prompt="prompts/extract.md",
            input="documents",
            mode="per_file",
            output="schemas/incident.yaml",
        )
    ],
)
# Not JSON at all, so the attempt fails validation and is retried (R6.2).
NONSENSE = "no JSON here"


def _abstains(document: str) -> str:
    """A valid answer for any document: it abstains, and says why (R6.5)."""
    return json.dumps(
        {
            "document": document,
            "fields": [
                {"field": "loss_amount", "value": None, "reason": "not stated in document"}
            ],
        }
    )


def _costing(text: str, input_tokens: int = 1204, output_tokens: int = 212) -> Reply:
    return Reply(text, input_tokens=input_tokens, output_tokens=output_tokens)


def _run(workspace: Path, model, *, run_id: str = RUN_ID, capture: str = "full") -> FakeTracker:
    """One run of `extract` over the three incidents; what it recorded."""
    from dossier.infrastructure.cache import ArtifactCache

    tracker = FakeTracker()
    execute(
        RunInputs(
            pipeline=CONFIG,
            pipeline_hash="6e0d4b27" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            documents=SNAPSHOTS,
            document_text=ISSUES,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
        recording=RunRecording(
            tracker=tracker, experiment="dossier-audit/incident-audit/run", capture=capture
        ),
    )
    return tracker


def _llm_spans(tracker: FakeTracker) -> list[dict]:
    return [span for span in tracker.spans if span["kind"] == "llm"]


class TestARunRecordsTheTokensItSpent:
    """R11.20 — a run's record holds the tokens it spent, and each LLM span carries
    its call's tokens where MLflow reads them."""

    def test_the_run_and_every_call_say_what_they_cost(self, tmp_path: Path):
        """Row 1: the one where three documents are asked at 1204/212 each."""
        model = FakeModelClient(
            responses=[_costing(_abstains(key)) for key in sorted(SNAPSHOTS)]
        )

        tracker = _run(tmp_path, model)

        (run,) = tracker.runs
        assert run.metrics["tokens_in"] == 3612
        assert run.metrics["tokens_out"] == 636
        assert [span[USAGE] for span in _llm_spans(tracker)] == [
            {"input_tokens": 1204, "output_tokens": 212, "total_tokens": 1416}
        ] * 3

    def test_a_retry_is_its_own_cost_and_the_run_holds_the_sum(self, tmp_path: Path):
        """Row 2: the one where `INC-4822` is valid on its second attempt at 1391/230."""
        model = FakeModelClient(
            responses=[
                _costing(_abstains("INC-4821")),
                _costing(NONSENSE),
                _costing(_abstains("INC-4822"), 1391, 230),
                _costing(_abstains("INC-4901")),
            ]
        )

        tracker = _run(tmp_path, model)

        (retried,) = [
            trace for trace in tracker.traces if trace.tags["dossier.document"] == "INC-4822"
        ]
        asked = [span[USAGE]["input_tokens"] for span in retried.spans if span["kind"] == "llm"]
        assert asked == [1204, 1391]
        (run,) = tracker.runs
        assert run.metrics["tokens_in"] == 1204 + 1204 + 1391 + 1204
        assert run.metrics["tokens_out"] == 212 + 212 + 230 + 212

    def test_a_count_is_recorded_under_hashes_as_under_full(self, tmp_path: Path):
        """Row 3: the one with `DOSSIER_MLFLOW_CAPTURE=hashes`: counts, and no text."""
        model = FakeModelClient(
            responses=[_costing(_abstains(key)) for key in sorted(SNAPSHOTS)]
        )

        tracker = _run(tmp_path, model, capture="hashes")

        for span in _llm_spans(tracker):
            assert span[USAGE] == {
                "input_tokens": 1204,
                "output_tokens": 212,
                "total_tokens": 1416,
            }
            assert "prompt" not in span and "reply" not in span

    def test_a_run_that_asked_nothing_spent_nothing(self, tmp_path: Path):
        """Row 4, a counter-example: the same run again, every document from cache."""
        first = FakeModelClient(
            responses=[_costing(_abstains(key)) for key in sorted(SNAPSHOTS)]
        )
        _run(tmp_path, first)

        tracker = _run(tmp_path, NoModelClient(), run_id=SECOND_RUN)

        (run,) = tracker.runs
        assert _llm_spans(tracker) == []
        assert run.metrics["tokens_in"] == 0
        assert run.metrics["tokens_out"] == 0

    def test_a_count_nobody_gave_is_missing_not_zero(self, tmp_path: Path):
        """Row 5, a counter-example: the one where the provider reports nothing."""
        model = FakeModelClient(responses=[_abstains(key) for key in sorted(SNAPSHOTS)])

        tracker = _run(tmp_path, model)

        (run,) = tracker.runs
        assert "tokens_in" not in run.metrics
        assert "tokens_out" not in run.metrics
        assert all(USAGE not in span for span in _llm_spans(tracker))

    def test_half_a_count_is_not_recorded_as_one(self):
        """Row 6, a counter-example: the one where only the input was counted."""
        from dossier.domain.tracking import token_metrics, token_usage
        from dossier.domain.usage import Tokens

        for half in (Tokens(input=1204, output=None), Tokens(input=None, output=212)):
            assert token_usage(half) is None
            assert token_metrics(half) == {}
