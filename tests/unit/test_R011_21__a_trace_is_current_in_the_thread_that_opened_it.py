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

import threading

from tests.fakes import FakeTracker

from dossier.infrastructure.tracking.best_effort import BestEffortTracker

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
