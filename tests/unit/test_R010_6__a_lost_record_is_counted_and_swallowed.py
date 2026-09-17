"""R10.6 — a record lost after the startup check never changes a command's
outcome. The adapter.

The acceptance test beside this one drives a whole command with a server that
stops answering. This one proves the adapter's rule with nothing but an inner
tracker that raises: every call is sent, every failure is swallowed, and a trace
any of whose calls failed is counted as lost -- so the command can say how many,
since a silent gap in MLflow would read as documents that were never processed.
"""

from __future__ import annotations

from tests.fakes import FakeTracker

from dossier.infrastructure.tracking.best_effort import BestEffortTracker


class FailingAfter(FakeTracker):
    """A tracker whose server stops answering after `calls` calls."""

    def __init__(self, calls: int) -> None:
        super().__init__()
        self._remaining = calls

    def _tick(self) -> None:
        if self._remaining <= 0:
            raise ConnectionError("server gone")
        self._remaining -= 1

    def start_run(self, **kwargs) -> None:
        self._tick()
        super().start_run(**kwargs)

    def start_trace(self, **kwargs) -> None:
        self._tick()
        super().start_trace(**kwargs)

    def span(self, **kwargs) -> None:
        self._tick()
        super().span(**kwargs)

    def end_trace(self, **kwargs) -> None:
        self._tick()
        super().end_trace(**kwargs)

    def end_run(self, **kwargs) -> None:
        self._tick()
        super().end_run(**kwargs)


def _four_traces(tracker: BestEffortTracker) -> None:
    tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})
    for key in ("INC-4821", "INC-4822", "INC-4901", "INC-5455"):
        tracker.start_trace(name=f"extract · {key}", tags={"dossier.document": key})
        tracker.span(kind="llm", name="m", attributes={})
        tracker.end_trace(status="OK")
    tracker.end_run(status="FINISHED")


class TestALostRecordIsCountedAndSwallowed:
    """R10.6 — after the startup check, a record lost is never a run lost."""

    def test_a_server_that_stops_answering_loses_traces_and_raises_nothing(self):
        """Example 1: the one where the server stops after the second of four traces.

        The run is one call, each trace three; the server answers seven calls
        and then none. Two traces made it whole, two did not, and nothing
        raised through to the command.
        """
        tracker = BestEffortTracker(FailingAfter(calls=7))

        _four_traces(tracker)

        assert tracker.lost_traces == 2

    def test_a_trace_is_lost_if_any_one_of_its_calls_failed(self):
        """The boundary: the one where only a trace's last call failed.

        One failure inside a trace is one lost trace, not a fraction of one; a
        trace half in MLflow would read as a document half processed.
        """
        tracker = BestEffortTracker(FailingAfter(calls=3))

        _four_traces(tracker)

        assert tracker.lost_traces == 4, "the third call was the first trace's end"

    def test_a_server_that_keeps_answering_loses_nothing(self):
        """Counter-example: the one where every call lands."""
        inner = FakeTracker()
        tracker = BestEffortTracker(inner)

        _four_traces(tracker)

        assert tracker.lost_traces == 0
        assert len(inner.traces) == 4
