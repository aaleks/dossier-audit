"""A tracker whose failures, once a command is under way, cost the record only (R10.6).

An adapter on the `Tracker` port, left of the hash boundary with the tracker it
wraps (R0.19). It reaches no network itself; it decides what a failure to
reach one means, which is the one decision spec 010 leaves to this side of the
port: after the startup check, a record lost is never a run lost.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping

from dossier.domain.ports import Tracker, VersionRegistry
from dossier.domain.tracking import MlflowAuth, refused_record
from dossier.domain.versions import PublishedVersion, VersionRecord

__all__ = ["BestEffortTracker", "BestEffortVersionRegistry"]


class BestEffortTracker:
    """A tracker whose failures, once a command is under way, cost the record only.

    The startup check has already refused a server nobody can reach (R10.5).
    After it, a server that stops answering is a record lost, not a run lost: the
    work completes, the answers are cached, and the command exits as it would
    have untracked (R10.6). So every call is sent, and any failure is swallowed
    -- a trace any of whose calls failed is counted as lost, and the command
    says how many at the end, since a silent gap in MLflow would read as
    documents that were never processed.

    A trace whose every call returned can still be lost: MLflow's exporter sends
    it later, and the server may refuse it. The tracker it wraps says which, as
    the record closes, in `unrecorded_traces` -- the places of those traces among
    the ones the run opened -- and each is counted here once, however many ways
    it was lost (R10.24).

    A run's workers record their documents at once (R11.21), so what belongs to
    one trace -- its place, and whether any of its calls failed -- is held per
    thread, and what belongs to the run is changed under a lock.
    """

    def __init__(
        self,
        inner: Tracker,
        *,
        warn: Callable[[str], None] | None = None,
        auth: MlflowAuth | None = None,
    ) -> None:
        self._inner = inner
        # Where a loss is said: the command's terminal, handed in by the
        # composition root. The wrapper decides what was lost; it prints nothing.
        self._warn = warn
        # The credential in force, so a refusal can name its variable (R10.22).
        self._auth = auth or MlflowAuth()
        self._experiment = ""
        self._refusal_said = False
        self.lost_records = 0
        # By place among the traces the run opened, so a trace lost by its own
        # call and not found on the server either is one trace (R10.24 row 4).
        self._lost_traces: set[int] = set()
        self._opened = 0
        # This thread's trace: its place, and whether a call of it failed.
        self._this_trace = threading.local()
        # Reentrant, because a trace is opened under it and a failure to open
        # one is counted under it too.
        self._lock = threading.RLock()

    @property
    def lost_traces(self) -> int:
        return len(self._lost_traces)

    def _sent(self, call, /, *args, **kwargs) -> bool:
        try:
            call(*args, **kwargs)
        except Exception as error:
            with self._lock:
                self.lost_records += 1
                self._said_if_refused(error)
            return False
        return True

    def _said_if_refused(self, error: Exception) -> None:
        """The first 401 or 403, said as it happens and once (R10.22).

        A refusal is configuration a person can fix, and on `dossier run` this is
        before the first model call. A server that has gone away -- no answer, a
        503 -- tells them nothing they can fix from the terminal, so it is only
        counted (R10.21). MLflow's exception is recognised by what it answers to,
        so nothing here imports MLflow.
        """
        status = getattr(error, "get_http_status_code", None)
        status = status() if callable(status) else None
        if status not in (401, 403) or self._refusal_said or self._warn is None:
            return
        self._refusal_said = True
        said = refused_record(self._auth, status=status, experiment=self._experiment)
        self._warn(f"warning: {said}")

    def start_run(self, *, experiment: str, name: str, tags: Mapping[str, str]) -> None:
        self._experiment = experiment
        self._sent(self._inner.start_run, experiment=experiment, name=name, tags=tags)

    def log_params(self, params: Mapping[str, str]) -> None:
        self._sent(self._inner.log_params, params)

    def log_metrics(self, metrics: Mapping[str, float]) -> None:
        self._sent(self._inner.log_metrics, metrics)

    def assess(self, *, name: str, value: bool, rationale: str, source: str) -> None:
        self._sent(
            self._inner.assess, name=name, value=value, rationale=rationale, source=source
        )

    def describe(self, text: str) -> None:
        self._sent(self._inner.describe, text)

    def produced_version(self, version_id: str) -> None:
        self._sent(self._inner.produced_version, version_id)

    def rendered_prompt(self, *, name: str, version: int) -> None:
        self._sent(self._inner.rendered_prompt, name=name, version=version)

    def scored_version(self, version_id: str) -> None:
        self._sent(self._inner.scored_version, version_id)

    def version_prompt(self, *, version_id: str, name: str, version: int) -> None:
        self._sent(
            self._inner.version_prompt, version_id=version_id, name=name, version=version
        )

    def log_version_metrics(self, *, version_id: str, metrics: Mapping[str, float]) -> None:
        self._sent(self._inner.log_version_metrics, version_id=version_id, metrics=metrics)

    def log_artifact(self, name: str, content: bytes) -> None:
        self._sent(self._inner.log_artifact, name, content)

    def log_dataset(self, *, name: str, dataset_id: str, digest: str) -> None:
        self._sent(self._inner.log_dataset, name=name, dataset_id=dataset_id, digest=digest)

    def start_trace(
        self,
        *,
        name: str,
        tags: Mapping[str, str],
        inputs: Mapping[str, object] | None = None,
    ) -> None:
        # Handed on only when there is one, so a tracker that shows no request
        # is called exactly as it was before R15.1.
        given = {} if inputs is None else {"inputs": inputs}
        # The place is taken and the trace opened under one lock, so the place
        # counted here is the place the tracker inside gives the same trace --
        # which is how it names one the server does not hold (R10.24, R11.21).
        with self._lock:
            place = self._opened
            self._opened += 1
            opened = self._sent(self._inner.start_trace, name=name, tags=tags, **given)
        self._this_trace.place = place
        self._this_trace.lost = not opened

    def span(self, *, kind: str, name: str, attributes: Mapping[str, object]) -> None:
        if not self._sent(self._inner.span, kind=kind, name=name, attributes=attributes):
            self._this_trace.lost = True

    def end_trace(
        self,
        *,
        status: str,
        error: str | None = None,
        outputs: object = None,
        tags: Mapping[str, str] | None = None,
    ) -> None:
        given = {} if outputs is None else {"outputs": outputs}
        if tags:
            given["tags"] = tags
        if not self._sent(self._inner.end_trace, status=status, error=error, **given):
            self._this_trace.lost = True
        if getattr(self._this_trace, "lost", False):
            with self._lock:
                self._lost_traces.add(self._this_trace.place)
        self._this_trace.lost = False

    def use_experiment(self, experiment: str) -> None:
        self._experiment = experiment
        self._sent(self._inner.use_experiment, experiment)

    def end_traces(self) -> None:
        """Close what `use_experiment` opened, counting what was lost as `end_run` does."""
        self._sent(self._inner.end_traces)
        self._count_lost()

    def end_run(self, *, status: str) -> None:
        self._sent(self._inner.end_run, status=status)
        self._count_lost()

    def _count_lost(self) -> None:
        # Read whether the close landed or not: the lookup is made before it.
        # Each trace not already counted is one record more (R10.24, R10.21).
        # Only a tracker that looks has anything to say, and reading what it says
        # must not raise where every call beside it is swallowed (R10.6).
        found = getattr(self._inner, "unrecorded_traces", frozenset())
        unheld = set(found if isinstance(found, frozenset) else ()) - self._lost_traces
        self._lost_traces |= unheld
        self.lost_records += len(unheld)
        # Said here because every command that records closes with this call, so
        # the line is the wrapper's to give and no command can forget it (R10.21).
        # After the close, so a close that was itself lost is in the count.
        if self.lost_records and self._warn is not None:
            self._warn(f"warning: {self.lost_records} record(s) could not be recorded")


class BestEffortVersionRegistry:
    """A version registry whose failures cost the record only (R13.5).

    `dossier run` fetches nothing, converts nothing and asks no model
    differently because MLflow is down. R10.6 already promises that of the
    tracker; this is the same promise for the second port on the same code path,
    and it has to be made separately because this one **returns** -- a caller
    that got `None` back and used it would fail for a different reason a line
    later.

    So a failure gives `None`, and the caller's `if version is None` is the
    whole of what it costs. The gap is counted and said out loud, as a lost
    trace is: a Models tab with nothing in it should not read as a pipeline
    nobody ever ran.
    """

    def __init__(self, inner: VersionRegistry) -> None:
        self._inner = inner
        self.lost_versions = 0

    def register(self, *, record: VersionRecord, experiment: str) -> PublishedVersion | None:
        try:
            return self._inner.register(record=record, experiment=experiment)
        except Exception:
            self.lost_versions += 1
            return None
