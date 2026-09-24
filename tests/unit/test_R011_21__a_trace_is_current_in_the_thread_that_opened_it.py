"""R11.21 — a run asking about several documents at once records each one's
trace holding only its own spans, and says how many it asked at once.

The port's half, without a run: two documents' traces opened at once, from two
threads in lockstep -- both opened, then both recording a span, then both
closed -- which is the order that sends every span to the last trace opened
when a tracker holds one current trace for the whole process. Each tracker
the port is handed must keep them apart: the fake, or it could not fail when
the real one broke the promise.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fakes import FakeTracker
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.tracking.best_effort import BestEffortTracker
from dossier.infrastructure.tracking.mlflow import MlflowTracker

MODEL = "anthropic:claude-sonnet-4-5-20250929"
DOCUMENTS = ("INC-4821", "INC-4822")


def _two_documents_at_once(tracker, documents: tuple[str, ...] = DOCUMENTS) -> None:
    """Two workers, each opening its trace, recording a span and closing, in lockstep.

    The traces are opened in the order `documents` names, so which place each
    holds among the traces opened is known to the test.
    """
    step = threading.Barrier(len(documents))
    opened = [threading.Event() for _ in documents]
    failures: list[BaseException] = []

    def document(place: int, key: str) -> None:
        try:
            if place:
                opened[place - 1].wait(timeout=5)
            tracker.start_trace(name=f"extract · {key}", tags={"dossier.document": key})
            opened[place].set()
            step.wait(timeout=5)
            tracker.span(kind="llm", name=MODEL, attributes={"document": key})
            step.wait(timeout=5)
            tracker.end_trace(status="OK" if key == "INC-4821" else "ERROR", error=None)
        except BaseException as error:  # pragma: no cover - reported below
            failures.append(error)

    workers = [
        threading.Thread(target=document, args=(place, key))
        for place, key in enumerate(documents)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    assert not failures, failures


class TestATraceIsCurrentInTheThreadThatOpenedIt:
    """R11.21 — what the `Tracker` port promises about traces opened at once."""

    def test_the_fake_keeps_each_documents_span_in_its_own_trace(self):
        """Row 1, on the fake: each trace holds one span, about its own document."""
        tracker = FakeTracker()
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})

        _two_documents_at_once(tracker)

        held = {trace.tags["dossier.document"]: trace for trace in tracker.traces}
        assert sorted(held) == list(DOCUMENTS)
        for key, trace in held.items():
            assert [span["document"] for span in trace.spans] == [key]
        assert held["INC-4821"].status == "OK"
        assert held["INC-4822"].status == "ERROR"

    def test_a_thread_that_opened_no_trace_records_to_none(self):
        """The fake's boundary: a span from a thread with no trace open is a defect, said so."""
        from tests.fakes import FakeTrackerError

        tracker = FakeTracker()
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})
        tracker.start_trace(name="extract · INC-4821", tags={"dossier.document": "INC-4821"})
        raised: list[BaseException] = []

        def elsewhere() -> None:
            try:
                tracker.span(kind="llm", name=MODEL, attributes={})
            except FakeTrackerError as error:
                raised.append(error)

        worker = threading.Thread(target=elsewhere)
        worker.start()
        worker.join(timeout=5)

        assert len(raised) == 1
        assert tracker.traces[0].spans == []


class LosesOneTrace(FakeTracker):
    """One of `document`'s own calls fails (R10.6), and the server does not hold
    that trace either (R10.24): the same trace lost two ways.

    The server's answer is by place among the traces opened, as `MlflowTracker`
    gives it, read off the order this fake saw them opened in.
    """

    def __init__(self, document: str) -> None:
        super().__init__()
        self.document = document
        self.unrecorded_traces: frozenset[int] = frozenset()

    def span(self, *, kind: str, name: str, attributes) -> None:
        super().span(kind=kind, name=name, attributes=attributes)
        if self._trace.tags["dossier.document"] == self.document:
            raise RuntimeError("the server stopped answering")

    def end_run(self, *, status) -> None:
        super().end_run(status=status)
        self.unrecorded_traces = frozenset(
            place
            for place, trace in enumerate(self.traces)
            if trace.tags["dossier.document"] == self.document
        )


class TestTheWrapperCountsWhatEachThreadLost:
    """R11.21 row 4, on `BestEffortTracker`: a trace lost on one worker is that trace."""

    def test_a_trace_lost_two_ways_is_counted_once(self):
        """Row 4: `INC-4822`'s span fails and the server does not hold its trace.

        Opened first, so it holds place 0 while `INC-4821` is the last trace
        opened: a wrapper that took the place of whichever trace was opened last
        would name `INC-4821`'s, and count one trace lost as two.
        """
        inner = LosesOneTrace("INC-4822")
        tracker = BestEffortTracker(inner)
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})

        _two_documents_at_once(tracker, ("INC-4822", "INC-4821"))
        tracker.end_run(status="FINISHED")

        assert inner.unrecorded_traces == frozenset({0})
        assert tracker.lost_traces == 1
        assert tracker.lost_records == 1


class Client:
    """`MlflowClient`, as far as a run's traces go, opened from several threads.

    It remembers which trace each span was started in and under which parent,
    which is what a tracker holding one current trace for the process gets
    wrong. What it holds, it holds by the document each trace was opened for.
    """

    def __init__(self) -> None:
        self.documents: dict[str, str] = {}
        self.spans: list[tuple[str, str, str]] = []
        self.ended: dict[str, str] = {}
        self._lock = threading.Lock()

    def get_experiment_by_name(self, name):
        return None

    def create_experiment(self, name):
        return "1"

    def create_run(self, experiment_id, tags=None, run_name=None):
        return SimpleNamespace(info=SimpleNamespace(run_id="run-1"))

    def start_trace(self, *, name, tags, experiment_id, run_id):
        with self._lock:
            trace_id = f"tr-{len(self.documents)}"
            self.documents[trace_id] = tags["dossier.document"]
        return SimpleNamespace(trace_id=trace_id, span_id=f"root-{trace_id}")

    def start_span(self, *, name, trace_id, parent_id, span_type, attributes):
        with self._lock:
            self.spans.append((trace_id, parent_id, attributes["document"]))
        return SimpleNamespace(span_id="child")

    def end_span(self, trace_id, span_id):
        pass

    def end_trace(self, trace_id, attributes=None, status=None):
        with self._lock:
            self.ended[self.documents[trace_id]] = status

    def search_traces(self, *, locations, run_id, include_spans, max_results, **kwargs):
        held = [trace_id for trace_id, key in self.documents.items() if key == "INC-4821"]
        return [SimpleNamespace(info=SimpleNamespace(trace_id=trace_id)) for trace_id in held]

    def set_terminated(self, run_id, status=None):
        pass


@pytest.fixture
def client(monkeypatch) -> Client:
    mlflow = pytest.importorskip("mlflow")

    stand_in = Client()
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(mlflow, "MlflowClient", lambda tracking_uri=None: stand_in)
    monkeypatch.setattr(mlflow, "flush_trace_async_logging", lambda *a, **k: None)
    return stand_in


class TestMlflowKeepsEachThreadsTrace:
    """R11.21 row 1, on `MlflowTracker`: what reaches MLflow, trace by trace."""

    def test_each_span_is_started_in_its_own_documents_trace(self, client: Client):
        """Row 1: two traces open at once, each span under its own trace's root."""
        tracker = MlflowTracker("http://localhost:5000")
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})

        _two_documents_at_once(tracker)

        assert sorted(document for _, _, document in client.spans) == list(DOCUMENTS)
        for trace_id, parent_id, document in client.spans:
            assert client.documents[trace_id] == document
            assert parent_id == f"root-{trace_id}"
        assert client.ended == {"INC-4821": "OK", "INC-4822": "ERROR"}

    def test_a_trace_the_server_lacks_is_named_by_the_place_it_was_opened_in(
        self, client: Client
    ):
        """Row 4's other half: the server holds `INC-4821` alone, opened second.

        The place is where the trace was opened among the run's, whichever
        thread opened it, so it is the place the wrapper counts (R10.24).
        """
        tracker = MlflowTracker("http://localhost:5000")
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})

        _two_documents_at_once(tracker, ("INC-4822", "INC-4821"))
        tracker.end_run(status="FINISHED")

        assert tracker.unrecorded_traces == frozenset({0})


class Abstaining:
    """A model that abstains for whichever document it is asked about (R6.5)."""

    model_id = MODEL

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        document = re.search(r'<document key="([^"]+)">', prompt).group(1)
        return json.dumps(
            {
                "document": document,
                "fields": [
                    {"field": "loss_amount", "value": None, "reason": "not stated in document"}
                ],
            }
        )


def _recorded_run(workspace: Path, **options) -> FakeTracker:
    """One run of `extract` over three incidents, recorded to a fake."""
    from dossier.infrastructure.cache import ArtifactCache

    tracker = FakeTracker()
    execute(
        workspace=workspace,
        pipeline=PipelineConfig(
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
        ),
        pipeline_hash="6e0d4b27" * 8,
        documents={
            "INC-4821": "a3f9c1e2" * 8,
            "INC-4822": "77c1b40a" * 8,
            "INC-4901": "0e52dd18" * 8,
        },
        document_text=ISSUES,
        schemas={
            "extract": OutputSchema(schema={"type": "object"}, declaration_hash="d24c86e1" * 8)
        },
        prompts={"extract": prompt_for(["documents"])},
        model=Abstaining(),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id="20260806T142203Z-4f1a",
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
        tracker=tracker,
        experiment="dossier-audit/incident-audit/run",
        **options,
    )
    return tracker


class TestTheRunSaysHowManyItAskedAtOnce:
    """R11.21 row 3: `concurrency` is a param of the run's record."""

    def test_three_at_once_is_recorded_as_three(self, tmp_path: Path):
        """Row 3: the one at `--concurrency 3`."""
        (run,) = _recorded_run(tmp_path, concurrency=3).runs

        assert run.params["concurrency"] == "3"

    def test_one_at_a_time_is_recorded_as_one(self, tmp_path: Path):
        """Row 3: the one where nothing sets it: `1`, a value rather than an absence."""
        (run,) = _recorded_run(tmp_path).runs

        assert run.params["concurrency"] == "1"
