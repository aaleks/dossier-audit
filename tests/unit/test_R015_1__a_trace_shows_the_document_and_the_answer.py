"""R15.1 — a run's trace shows the document it read as its request and the
answer it gave as its response.

The decision is the domain's: what a trace's request and response are under
each capture setting (`trace_request`, `trace_response`). Then the run, through
`execute` and a `FakeTracker`, which keeps what each trace was opened with and
closed with; and `MlflowTracker`, which must hand both to MLflow, where the
trace list shows them as its Request and Response columns (verified live before
spec 015 was written).

The pipeline is `extract` -> `verify` -> `report` over two of the scoring
example's incidents, `INC-4822` answered with something that is not JSON twice,
so it fails (R6.2).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fakes import FakeModelClient, FakeTracker
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.run import RunInputs, RunRecording, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.hashing import content_hash
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.tracking import trace_request, trace_response

RUN_ID = "20260806T142203Z-4f1a"
WRAPPED = '<document key="INC-4821">\n# INC-4821\n</document>'
ANSWER = '{\n  "document": "INC-4821",\n  "fields": []\n}\n'
NONSENSE = "no JSON here"
PROSE = "Two incidents; one failed validation."


class TestWhatATraceShows:
    """R15.1 — the request and the response, decided once for every capture."""

    def test_the_request_is_the_document_and_what_it_was_handed(self):
        """Row 1: the key, and each value under its input's name."""
        assert trace_request("INC-4821", {"documents": WRAPPED}, capture="full") == {
            "document": "INC-4821",
            "inputs": {"documents": WRAPPED},
        }

    def test_a_structured_answer_is_shown_as_json(self):
        """Row 1: the field record, parsed, so MLflow renders it rather than quoting it."""
        shown = trace_response(ANSWER, structured=True, error=None, capture="full")

        assert shown == {"document": "INC-4821", "fields": []}

    def test_prose_is_shown_as_prose(self):
        """Row 5: a step with no output answers in prose, shown as written."""
        assert trace_response(PROSE, structured=False, error=None, capture="full") == PROSE

    def test_a_failure_shows_its_error(self):
        """Row 4: nothing was answered, so the response is what went wrong."""
        shown = trace_response(None, structured=True, error="invalid JSON", capture="full")

        assert shown == {"error": "invalid JSON"}
        # Where the model did answer, and the answer failed validation, the error
        # is still the response: an answer that was refused is not the answer.
        answered = trace_response(
            "not json", structured=True, error="invalid JSON", capture="full"
        )
        assert answered == {"error": "invalid JSON"}

    def test_under_hashes_neither_holds_a_word(self):
        """Row 6, a counter-example: keys and hashes, and no text (R10.8)."""
        request = trace_request("INC-4821", {"documents": WRAPPED}, capture="hashes")
        response = trace_response(ANSWER, structured=True, error=None, capture="hashes")

        assert request == {
            "document": "INC-4821",
            "inputs": {"documents": content_hash(WRAPPED.encode("utf-8"))},
        }
        assert response == {"artifact": content_hash(ANSWER.encode("utf-8"))}
        assert "INC-4821\n" not in json.dumps([request, response])


def _abstains(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {"field": "loss_amount", "value": None, "reason": "not stated in document"}
            ],
        }
    )


def _run(workspace: Path, model, *, capture: str = "full", run_id: str = RUN_ID) -> FakeTracker:
    """`extract` -> `verify` -> `report` over `INC-4821` and `INC-4822`, recorded."""
    from dossier.infrastructure.cache import ArtifactCache

    declared = OutputSchema(schema={"type": "object"}, declaration_hash="d24c86e1" * 8)
    tracker = FakeTracker()
    execute(
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
                    ),
                    StepConfig(
                        id="verify",
                        prompt="prompts/verify.md",
                        input=["documents", "extract"],
                        mode="per_file",
                        output="schemas/incident.yaml",
                    ),
                    StepConfig(
                        id="report",
                        prompt="prompts/report.md",
                        input="verify",
                        mode="aggregate",
                    ),
                ],
            ),
            pipeline_hash="6e0d4b27" * 8,
            schemas={"extract": declared, "verify": declared, "report": None},
            prompts={
                "extract": prompt_for(["documents"]),
                "verify": prompt_for(["documents", "extract"]),
                "report": prompt_for(["verify"]),
            },
            documents={"INC-4821": "a3f9c1e2" * 8, "INC-4822": "77c1b40a" * 8},
            document_text={key: ISSUES[key] for key in ("INC-4821", "INC-4822")},
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


def _answers() -> FakeModelClient:
    return FakeModelClient(
        responses=[_abstains("INC-4821"), NONSENSE, NONSENSE, _abstains("INC-4821"), PROSE]
    )


def _trace(tracker: FakeTracker, name: str):
    (trace,) = [trace for trace in tracker.traces if trace.name == name]
    return trace


class TestARunShowsWhatEachTraceReadAndAnswered:
    """R15.1 — through `execute`: each trace opened with its request, closed with its answer."""

    def test_a_step_shows_its_document_and_its_answer(self, tmp_path: Path):
        """Row 1: `extract · INC-4821`, the answer as `runs/` holds it."""
        tracker = _run(tmp_path, _answers())

        trace = _trace(tracker, "extract · INC-4821")
        assert trace.inputs["document"] == "INC-4821"
        assert list(trace.inputs["inputs"]) == ["documents"]
        assert trace.inputs["inputs"]["documents"].startswith('<document key="INC-4821">')
        written = tmp_path / "runs" / RUN_ID / "extract" / "INC-4821.json"
        assert trace.outputs == json.loads(written.read_text(encoding="utf-8"))

    def test_a_step_reading_two_inputs_shows_both(self, tmp_path: Path):
        """Row 2: `verify · INC-4821` reads the document and `extract`'s answer."""
        tracker = _run(tmp_path, _answers())

        shown = _trace(tracker, "verify · INC-4821").inputs["inputs"]
        assert list(shown) == ["documents", "extract"]
        assert '"document": "INC-4821"' in shown["extract"]

    def test_an_answer_served_from_cache_is_shown_as_it_was_given(self, tmp_path: Path):
        """Row 3: the same run again, every document served from cache."""
        first = _run(tmp_path, _answers())
        again = _run(
            tmp_path,
            FakeModelClient(responses=[NONSENSE, NONSENSE]),
            run_id="20260807T090000Z-bbbb",
        )

        before, after = _trace(first, "extract · INC-4821"), _trace(again, "extract · INC-4821")
        assert (after.inputs, after.outputs) == (before.inputs, before.outputs)

    def test_a_document_that_failed_shows_its_error(self, tmp_path: Path):
        """Row 4: `INC-4822`, not JSON twice."""
        tracker = _run(tmp_path, _answers())

        trace = _trace(tracker, "extract · INC-4822")
        assert trace.status == "ERROR"
        assert trace.outputs == {"error": trace.error}

    def test_prose_is_shown_as_the_report_wrote_it(self, tmp_path: Path):
        """Row 5: `report`, an aggregate step with no output."""
        tracker = _run(tmp_path, _answers())

        assert _trace(tracker, "report · *").outputs == PROSE

    def test_under_hashes_no_trace_holds_a_word(self, tmp_path: Path):
        """Row 6, a counter-example: `DOSSIER_MLFLOW_CAPTURE=hashes`."""
        tracker = _run(tmp_path, _answers(), capture="hashes")

        trace = _trace(tracker, "extract · INC-4821")
        (shown,) = trace.inputs["inputs"].values()
        assert len(shown) == 64 and set(shown) <= set("0123456789abcdef")
        assert set(trace.outputs) == {"artifact"}


class _Client:
    """`MlflowClient`, as far as one trace goes: what it was opened and closed with."""

    def __init__(self) -> None:
        self.opened: dict[str, object] = {}
        self.closed: dict[str, object] = {}

    def get_experiment_by_name(self, name):
        return None

    def create_experiment(self, name):
        return "1"

    def create_run(self, experiment_id, tags=None, run_name=None):
        return SimpleNamespace(info=SimpleNamespace(run_id="run-1"))

    def start_trace(self, *, name, tags, experiment_id, run_id, **given):
        self.opened = given
        return SimpleNamespace(trace_id="tr-0", span_id="root")

    def end_trace(self, trace_id, attributes=None, status=None, **given):
        self.closed = given


@pytest.fixture
def client(monkeypatch) -> _Client:
    mlflow = pytest.importorskip("mlflow")

    stand_in = _Client()
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(mlflow, "MlflowClient", lambda tracking_uri=None: stand_in)
    return stand_in


class TestMlflowIsHandedBoth:
    """R15.1 row 1, on `MlflowTracker`: where the trace list reads them."""

    def test_the_request_and_the_response_reach_mlflow(self, client: _Client):
        """Row 1: the trace's inputs and outputs, as MLflow takes them."""
        from dossier.infrastructure.tracking.mlflow import MlflowTracker

        tracker = MlflowTracker("http://localhost:5000")
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name=RUN_ID, tags={})
        request = {"document": "INC-4821", "inputs": {"documents": WRAPPED}}

        tracker.start_trace(name="extract · INC-4821", tags={}, inputs=request)
        tracker.end_trace(status="OK", outputs={"document": "INC-4821", "fields": []})

        assert client.opened == {"inputs": request}
        assert client.closed == {"outputs": {"document": "INC-4821", "fields": []}}

    def test_a_trace_opened_with_neither_hands_mlflow_neither(self, client: _Client):
        """The judge's and a calibration's traces, outside R15.1, are sent as before."""
        from dossier.infrastructure.tracking.mlflow import MlflowTracker

        tracker = MlflowTracker("http://localhost:5000")
        tracker.start_run(experiment="dossier-audit/incident-audit/eval", name=RUN_ID, tags={})

        tracker.start_trace(name="judge · INC-4821", tags={})
        tracker.end_trace(status="OK")

        assert (client.opened, client.closed) == ({}, {})
