"""R10.24 — every trace a command opened is looked for on the server as its record
closes, and one the server does not hold is lost.

`MlflowTracker` is built over `Server`, which stands in for `MlflowClient` and
MLflow's exporter together, as they behave: a trace is held in memory until it
ends, queued, and reaches the server only when the exporter sends it -- which
the flush waits for -- and a trace the server refuses is simply not there
afterwards. Nothing raises. That is the whole of why R10.6 could not count one.

What a lookup returns was read off a real store: `search_traces(locations=[...],
run_id=..., include_spans=False)` answers every trace carrying the run as
`mlflow.sourceRun`, and no spans. No socket is opened here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from dossier.infrastructure.tracking.mlflow import MlflowTracker

pytest.importorskip("mlflow")

URI = "http://localhost:5000"
RUN = "dossier-audit/incident-audit/run"
DOCUMENTS = ("INC-4821", "INC-4822", "INC-4823", "INC-4830")


@dataclass
class Server:
    """`MlflowClient` and MLflow's exporter, over one server's holdings."""

    refused: set[str] = field(default_factory=set)
    held: dict[str, str] = field(default_factory=dict)  # trace id -> run id
    queued: list[tuple[str, str, str]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    lookups: list[dict[str, object]] = field(default_factory=list)
    _traces: dict[str, tuple[str, str]] = field(default_factory=dict)

    # -- the client -------------------------------------------------------------

    def get_experiment_by_name(self, name):
        return None

    def create_experiment(self, name):
        return "1"

    def create_run(self, experiment_id, tags=None, run_name=None):
        self.calls.append("create_run")
        return SimpleNamespace(info=SimpleNamespace(run_id="run-1"))

    def start_trace(self, *, name, tags, experiment_id, run_id):
        trace_id = f"tr-{len(self._traces)}"
        self._traces[trace_id] = (name, run_id)
        return SimpleNamespace(trace_id=trace_id, span_id="root")

    def start_span(self, **kwargs):
        return SimpleNamespace(span_id="child")

    def end_span(self, trace_id, span_id):
        pass

    def end_trace(self, trace_id, attributes=None, status=None):
        name, run_id = self._traces[trace_id]
        self.queued.append((trace_id, name, run_id))

    def search_traces(self, *, locations, run_id, include_spans, max_results, **kwargs):
        self.calls.append("lookup")
        self.lookups.append(
            {"locations": locations, "run_id": run_id, "include_spans": include_spans}
        )
        return [
            SimpleNamespace(info=SimpleNamespace(trace_id=trace_id))
            for trace_id, owner in self.held.items()
            if owner == run_id
        ][:max_results]

    def set_terminated(self, run_id, status=None):
        self.calls.append("close")

    # -- the exporter -----------------------------------------------------------

    def flush(self, *args, **kwargs):
        """Send everything queued; a refused trace is dropped, as MLflow's worker drops it."""
        self.calls.append("flush")
        for trace_id, name, run_id in self.queued:
            if name not in self.refused:
                self.held[trace_id] = run_id
        self.queued = []


@pytest.fixture
def server(monkeypatch) -> Server:
    import mlflow

    stand_in = Server()
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(mlflow, "MlflowClient", lambda tracking_uri=None: stand_in)
    monkeypatch.setattr(mlflow, "flush_trace_async_logging", stand_in.flush)
    return stand_in


def a_run(tracker: MlflowTracker) -> None:
    """Four traces, one per incident, each with its stage span, then the close."""
    tracker.start_run(experiment=RUN, name="20260806T142203Z-4f1a", tags={})
    for document in DOCUMENTS:
        tracker.start_trace(name=f"verify · {document}", tags={})
        tracker.span(kind="stage", name="verify", attributes={})
        tracker.end_trace(status="OK")
    tracker.end_run(status="FINISHED")


class TestTheAdapterLooksForEveryTrace:
    """R10.24, on `MlflowTracker`: what the server holds, looked up as the record closes."""

    def test_the_traces_the_server_does_not_hold_are_named_by_their_place(self, server: Server):
        """Example 1: the one where the second and third were refused.

        By place among the traces the run opened, not by id: the port reads no
        id back from a server, so nothing MLflow holds can become an input (R0.10).
        """
        server.refused = {"verify · INC-4822", "verify · INC-4823"}
        tracker = MlflowTracker(URI)

        a_run(tracker)

        assert tracker.unrecorded_traces == frozenset({1, 2})
        assert server.lookups == [
            {"locations": ["1"], "run_id": "run-1", "include_spans": False}
        ]

    def test_a_record_that_opened_no_trace_looks_for_none(self, server: Server):
        """Counter-example 7: the one where `dossier sync` opens no trace.

        No flush and no lookup: a command without traces makes not one request
        more than it did before this rule.
        """
        tracker = MlflowTracker(URI)

        tracker.start_run(experiment=RUN, name="sync 20260806T142203Z", tags={})
        tracker.end_run(status="FINISHED")

        assert server.calls == ["create_run", "close"]
        assert tracker.unrecorded_traces == frozenset()
