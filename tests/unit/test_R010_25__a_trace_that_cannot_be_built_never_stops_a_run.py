"""R10.25 — a document's trace, and each model call's span, never stops
`dossier run`: content that cannot be built is recorded as the error.

The content of a trace is built in the run's loop, before the best-effort
tracker (R10.6) is handed anything, so an exception there was the run's own: on
2026-09-29 one stopped every `per_part` run recorded to MLflow after its first
document (R15.6). Each builder is made to fail here, one at a time, by
replacing it where the run calls it -- the only way to make content that is
built correctly today fail on purpose.

Run through `execute` with a `FakeTracker`, which keeps what each trace was
opened and closed with and every span sent on it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, FakeTracker
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.run import RunInputs, RunRecording, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig

RUN_ID = "20260929T090000Z-cccc"
DOCUMENTS = ("INC-4821", "INC-4822")
UNBUILT = "could not be built: RuntimeError: boom"


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


def _run(workspace: Path, *, tracked: bool = True) -> tuple[FakeTracker, object]:
    """`extract` over two incidents, each answered once; the tracker and the report."""
    from dossier.infrastructure.cache import ArtifactCache

    tracker = FakeTracker()
    model = FakeModelClient(
        responses=[json.dumps({"document": key, "fields": []}) for key in DOCUMENTS]
    )
    report = execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit",
                sources=["incidents-jira"],
                model="anthropic:claude-sonnet-4-5-20250929",
                steps=[
                    StepConfig(
                        id="extract",
                        prompt="prompts/extract.md",
                        input="documents",
                        mode="per_file",
                        output="schemas/incident.yaml",
                    )
                ],
            ),
            pipeline_hash="6e0d4b27" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            documents={"INC-4821": "a3f9c1e2" * 8, "INC-4822": "77c1b40a" * 8},
            document_text={key: ISSUES[key] for key in DOCUMENTS},
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=RUN_ID,
        started_at=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
        dossier_version="0.1.0",
        # Untracked is no recording at all, as every run without MLflow is.
        **(
            {
                "recording": RunRecording(
                    tracker=tracker,
                    experiment="dossier-audit/incident-audit/run",
                    capture="full",
                )
            }
            if tracked
            else {}
        ),
    )
    return tracker, report


def _trace(tracker: FakeTracker, document: str):
    (trace,) = [trace for trace in tracker.traces if trace.name == f"extract · {document}"]
    return trace


def _completed(workspace: Path, report) -> None:
    """Both documents answered, written and cached, as a run with no tracking leaves them.

    Cached is read off the record beside each artifact: the key it names is one
    the stage cache holds, so the next run is served it (R5.5).
    """
    from dossier.infrastructure.cache import ArtifactCache

    (step,) = report.steps
    assert [result.document for result in step.results] == list(DOCUMENTS)
    assert not any(result.failed for result in step.results)
    cache = ArtifactCache(workspace, namespace="stage")
    for document in DOCUMENTS:
        written = workspace / "runs" / RUN_ID / "extract" / f"{document}.json"
        assert written.is_file()
        record = json.loads(written.with_name(f"{document}.meta.json").read_text("utf-8"))
        assert cache.get(record["cache_key"], require_record=True) is not None, document


class TestATraceThatCannotBeBuiltNeverStopsARun:
    """R10.25 — content that cannot be built is sent holding the error, and the run goes on."""

    def test_a_response_that_cannot_be_built_is_recorded_as_the_error(
        self, tmp_path: Path, monkeypatch
    ):
        """Row 1 — the one that stopped every per_part run: the response."""
        monkeypatch.setattr("dossier.application.run.trace_response", _boom)

        tracker, report = _run(tmp_path)

        _completed(tmp_path, report)
        trace = _trace(tracker, "INC-4821")
        assert trace.status == "OK"
        assert trace.outputs == {"error": UNBUILT}

    def test_a_request_that_cannot_be_built_is_recorded_as_the_error(
        self, tmp_path: Path, monkeypatch
    ):
        """Row 2 — the one where the trace is opened with the key and the error."""
        monkeypatch.setattr("dossier.application.run.trace_request", _boom)

        tracker, report = _run(tmp_path)

        _completed(tmp_path, report)
        assert _trace(tracker, "INC-4821").inputs == {"document": "INC-4821", "error": UNBUILT}

    def test_tags_that_cannot_be_built_put_the_trace_in_the_review_queue(
        self, tmp_path: Path, monkeypatch
    ):
        """Row 3 — the one where a doubt nobody could write down is still a doubt."""
        monkeypatch.setattr("dossier.application.run.review_tags", _boom)

        tracker, report = _run(tmp_path)

        _completed(tmp_path, report)
        tags = _trace(tracker, "INC-4821").tags
        assert tags["dossier.review"] == "needed"
        assert tags["dossier.findings"] == UNBUILT

    def test_a_span_that_cannot_be_built_is_still_sent(self, tmp_path: Path, monkeypatch):
        """Row 4 — the one where every call still has its span (R11.2)."""
        monkeypatch.setattr("dossier.application.extract.span_payload", _boom)

        tracker, report = _run(tmp_path)

        _completed(tmp_path, report)
        spans = [span for span in tracker.spans if span["kind"] == "llm"]
        assert len(spans) == len(DOCUMENTS)
        assert all(span["error"] == UNBUILT for span in spans)

    @pytest.mark.parametrize(
        "builder",
        [
            "dossier.application.run.trace_request",
            "dossier.application.run.trace_response",
            "dossier.application.run.review_tags",
            "dossier.application.extract.span_payload",
        ],
    )
    def test_with_tracking_off_nothing_is_built(self, tmp_path: Path, monkeypatch, builder):
        """Row 5, counter-example — the one where there is no trace to build (R10.4)."""
        called: list[str] = []
        monkeypatch.setattr(builder, lambda *args, **kwargs: called.append(builder))

        _, report = _run(tmp_path, tracked=False)

        _completed(tmp_path, report)
        assert called == []
