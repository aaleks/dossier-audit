"""A tracker whose failures, once a command is under way, cost the record only (R10.6).

An adapter on the `Tracker` port, left of the hash boundary with the tracker it
wraps (R0.10). It reaches no network itself; it decides what a failure to
reach one means, which is the one decision spec 010 leaves to this side of the
port: after the startup check, a record lost is never a run lost.
"""

from __future__ import annotations

from collections.abc import Mapping

from dossier.domain.ports import Tracker

__all__ = ["BestEffortTracker"]


class BestEffortTracker:
    """A tracker whose failures, once a command is under way, cost the record only.

    The startup check has already refused a server nobody can reach (R10.5).
    After it, a server that stops answering is a record lost, not a run lost: the
    work completes, the answers are cached, and the command exits as it would
    have untracked (R10.6). So every call is sent, and any failure is swallowed
    -- a trace any of whose calls failed is counted as lost, and the command
    says how many at the end, since a silent gap in MLflow would read as
    documents that were never processed.
    """

    def __init__(self, inner: Tracker) -> None:
        self._inner = inner
        self.lost_traces = 0
        self._this_trace_lost = False

    def _sent(self, call, /, *args, **kwargs) -> bool:
        try:
            call(*args, **kwargs)
        except Exception:
            return False
        return True

    def start_run(self, *, experiment: str, name: str, tags: Mapping[str, str]) -> None:
        self._sent(self._inner.start_run, experiment=experiment, name=name, tags=tags)

    def log_params(self, params: Mapping[str, str]) -> None:
        self._sent(self._inner.log_params, params)

    def log_metrics(self, metrics: Mapping[str, float]) -> None:
        self._sent(self._inner.log_metrics, metrics)

    def log_artifact(self, name: str, content: bytes) -> None:
        self._sent(self._inner.log_artifact, name, content)

    def log_dataset(self, *, name: str, dataset_id: str, digest: str) -> None:
        self._sent(self._inner.log_dataset, name=name, dataset_id=dataset_id, digest=digest)

    def start_trace(self, *, name: str, tags: Mapping[str, str]) -> None:
        self._this_trace_lost = not self._sent(self._inner.start_trace, name=name, tags=tags)

    def span(self, *, kind: str, name: str, attributes: Mapping[str, object]) -> None:
        if not self._sent(self._inner.span, kind=kind, name=name, attributes=attributes):
            self._this_trace_lost = True

    def end_trace(self, *, status: str, error: str | None = None) -> None:
        if not self._sent(self._inner.end_trace, status=status, error=error):
            self._this_trace_lost = True
        if self._this_trace_lost:
            self.lost_traces += 1
        self._this_trace_lost = False

    def end_run(self, *, status: str) -> None:
        self._sent(self._inner.end_run, status=status)
