"""R10.21 — every lost record is counted, and the count is said when the record closes.

`BestEffortTracker` swallows every failure after the startup check (R10.6). It now
also counts each one, and says the count through the `warn` it is handed when
the record is closed with `end_run` -- the one call every command that records
makes last. So the line is a property of the wrapper, and no command can forget
to print it.
"""

from __future__ import annotations

import pytest
from tests.fakes import FakeTracker

from dossier.infrastructure.tracking.best_effort import BestEffortTracker

EXPERIMENT = "dossier-audit/incident-audit/sync"


class Refusing(FakeTracker):
    """A server that answers the first `answers` calls, then stops."""

    def __init__(self, answers: int = 0) -> None:
        super().__init__()
        self.answers = answers

    def _maybe(self) -> None:
        if self.answers <= 0:
            raise ConnectionError(
                "the MLflow server at http://localhost:5000 stopped answering"
            )
        self.answers -= 1

    def start_run(self, **kwargs):
        self._maybe()
        return super().start_run(**kwargs)

    def log_params(self, params):
        self._maybe()
        return super().log_params(params)

    def log_metrics(self, metrics):
        self._maybe()
        return super().log_metrics(metrics)

    def log_artifact(self, name, content):
        self._maybe()
        return super().log_artifact(name, content)

    def describe(self, text):
        self._maybe()
        return super().describe(text)

    def end_run(self, *, status):
        self._maybe()
        return super().end_run(status=status)


def a_sync(tracker: BestEffortTracker) -> None:
    """The six records a `dossier sync` makes, in its order."""
    tracker.start_run(experiment=EXPERIMENT, name="sync 20260806T142203Z", tags={})
    tracker.log_params({"dossier_version": "0.1.0"})
    tracker.log_metrics({"incidents-jira.fetched": 4.0})
    tracker.log_artifact("changes.json", b"{}")
    tracker.describe("sync incident-audit")
    tracker.end_run(status="FINISHED")


class TestEveryLostRecordIsCounted:
    """R10.21 — counted, and said once, at the close."""

    def test_six_lost_records_are_said_once_at_the_close(self):
        """Example 1: the one where the server stopped answering after the startup check."""
        said: list[str] = []
        tracker = BestEffortTracker(Refusing(), warn=said.append)

        a_sync(tracker)

        assert tracker.lost_records == 6
        assert said == ["warning: 6 record(s) could not be recorded"]

    def test_records_lost_part_way_are_counted_from_where_they_stopped(self):
        """The one where the first three records land and the last three do not."""
        said: list[str] = []
        tracker = BestEffortTracker(Refusing(answers=3), warn=said.append)

        a_sync(tracker)

        assert said == ["warning: 3 record(s) could not be recorded"]

    def test_nothing_lost_says_nothing(self):
        """Counter-example 4: no line, not `0 record(s)`."""
        said: list[str] = []
        tracker = BestEffortTracker(FakeTracker(), warn=said.append)

        a_sync(tracker)

        assert tracker.lost_records == 0
        assert said == []

    def test_a_lost_trace_is_a_lost_record_too(self):
        """Example 2's count: a run's lost trace calls are in its record count as well."""

        class TracesRefused(FakeTracker):
            def start_trace(self, **kwargs):
                raise ConnectionError("stopped answering")

            def span(self, **kwargs):
                raise ConnectionError("stopped answering")

            def end_trace(self, **kwargs):
                raise ConnectionError("stopped answering")

        said: list[str] = []
        tracker = BestEffortTracker(TracesRefused(), warn=said.append)
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})
        tracker.start_trace(name="verify · INC-4821", tags={})
        tracker.span(kind="stage", name="verify", attributes={})
        tracker.end_trace(status="OK")
        tracker.end_run(status="FINISHED")

        assert (tracker.lost_traces, tracker.lost_records) == (1, 3)
        assert said == ["warning: 3 record(s) could not be recorded"]

    @pytest.mark.parametrize("answers", [0, 5])
    def test_without_a_warn_the_count_is_kept_and_nothing_is_said(self, answers):
        """The wrapper decides what was lost; the command decides where it is said."""
        tracker = BestEffortTracker(Refusing(answers=answers))

        a_sync(tracker)

        assert tracker.lost_records == 6 - answers
