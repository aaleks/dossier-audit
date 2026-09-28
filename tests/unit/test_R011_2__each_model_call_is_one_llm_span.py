"""R11.2 — each model call is exactly one LLM span.

The trace and `FakeModelClient`'s call count are the same claim seen twice
(R5.5): a model call that left no span would be a cost nobody can see, and a span
with no call behind it would be a cost that never happened. A retry is its own
call, so it is its own span, and the first one carries the validation error it
was retried on (R6.2). A cache hit is still a trace, with no LLM span in it:
seeing that a document cost nothing is information (spec 011).

`execute` is run directly, with a `FakeTracker` counting what was recorded and a
`FakeModelClient` counting what was asked. The four incidents are the scoring
example's.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient, FakeTracker, NoModelClient
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.run import RunInputs, RunRecording, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

MODEL = "anthropic:claude-sonnet-4-5-20250929"
RUN_ID = "20260806T142203Z-4f1a"
SNAPSHOTS = {
    "INC-4821": "a3f9c1e2" * 8,
    "INC-4822": "77c1b40a" * 8,
    "INC-4901": "0e52dd18" * 8,
    "INC-5455": "c4a70b93" * 8,
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


def _run(workspace: Path, model, run_id: str = RUN_ID) -> FakeTracker:
    """One run of `extract` over the four incidents; what it recorded."""
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
        recording=RunRecording(tracker=tracker, experiment="dossier-audit/incident-audit/run"),
    )
    return tracker


def _llm_spans(trace) -> list[dict]:
    return [span for span in trace.spans if span["kind"] == "llm"]


class TestEachModelCallIsOneLLMSpan:
    """R11.2 — each model call is exactly one LLM span."""

    def test_four_documents_nothing_cached_is_four_llm_spans_one_per_call(self, tmp_path: Path):
        """Example 1: the one where every document is asked once."""
        model = FakeModelClient(responses=[_abstains(key) for key in sorted(SNAPSHOTS)])

        tracker = _run(tmp_path, model)

        assert len([span for span in tracker.spans if span["kind"] == "llm"]) == 4
        assert model.call_count == 4

    def test_a_retry_is_its_own_span_and_the_first_carries_the_error(self, tmp_path: Path):
        """Example 2: the one where `INC-4822` is valid on its second attempt.

        Two calls for that document, so two LLM spans in its trace. The first
        carries the validation error it was retried on; the second, which
        validated, carries none.
        """
        model = FakeModelClient(
            responses=[
                _abstains("INC-4821"),
                '{"document": "INC-4822", "fields": [{"not_a_field": true}]}',
                _abstains("INC-4822"),
                _abstains("INC-4901"),
                _abstains("INC-5455"),
            ]
        )

        tracker = _run(tmp_path, model)

        by_document = {trace.tags["dossier.document"]: trace for trace in tracker.traces}
        retried = _llm_spans(by_document["INC-4822"])
        assert len(retried) == 2
        assert retried[0].get("error")
        assert not retried[1].get("error")
        assert model.call_count == 5

    def test_a_run_served_from_cache_has_a_trace_per_document_and_no_llm_span(
        self, tmp_path: Path
    ):
        """Counter-example (row 3): the one run again, every result from cache.

        Four traces, because four keys were served; no LLM span, because nothing
        was asked. Each stage span says it was a hit, and which key it was.
        """
        first = FakeModelClient(responses=[_abstains(key) for key in sorted(SNAPSHOTS)])
        _run(tmp_path, first)

        tracker = _run(tmp_path, NoModelClient(), run_id="20260806T152203Z-4f1a")

        assert len(tracker.traces) == 4
        assert [span for span in tracker.spans if span["kind"] == "llm"] == []
        stages = [span for span in tracker.spans if span["kind"] == "stage"]
        assert len(stages) == 4
        assert all(span["dossier.cache"] == "hit" for span in stages)
        assert all(re.fullmatch(r"[0-9a-f]{64}", span["dossier.key"]) for span in stages)
