"""The MLflow tracker, and the check that it can record at all (spec 010).

`connect` is called once, at startup, before any work (R10.5): with tracking
switched on, a server nobody can reach -- or the `tracking` extra not installed
-- refuses the command now, rather than after an hour of model calls nobody can
inspect. `mlflow` is imported only when tracking is on, so a machine without the
extra loses nothing it did not ask for.

`MlflowTracker` implements the `Tracker` port with `MlflowClient`. Every method
sends and returns nothing (R0.10); the ids MLflow assigns stay inside it.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

import httpx

from dossier.domain.ports import Tracker

# How the startup check reaches the server. `None` is a real connection; a test
# answers with an `httpx.MockTransport`, so no socket is opened (R0.10).
HEALTH_TRANSPORT: httpx.BaseTransport | None = None

# Long enough for a server under load to answer a health check, short enough
# that a wrong URI is reported before anyone wonders why nothing happened.
HEALTH_TIMEOUT_SECONDS = 5.0


class TrackingUnavailable(RuntimeError):
    """Tracking is switched on, and nothing can be recorded -- said before any work."""


def connect(uri: str) -> Tracker:
    """A tracker recording to `uri`, or `TrackingUnavailable` saying why not (R10.5).

    Two checks, in the order a person would fix them: the `tracking` extra is
    installed, and a server answers at an `http(s)` URI. A local store such as
    `sqlite:///mlflow.db` has no server to ask, so it is not asked.
    """
    try:
        import mlflow  # noqa: F401 -- the extra is what is being checked for
    except ImportError as error:
        raise TrackingUnavailable(
            "tracking is enabled and `mlflow` is not installed. Install the extra -- "
            "pip install 'dossier[tracking]' -- or set DOSSIER_MLFLOW_ENABLED=false."
        ) from error

    if uri.startswith(("http://", "https://")):
        health = uri.rstrip("/") + "/health"
        try:
            with httpx.Client(
                transport=HEALTH_TRANSPORT, timeout=HEALTH_TIMEOUT_SECONDS
            ) as http:
                answered = http.get(health)
        except httpx.HTTPError as error:
            raise TrackingUnavailable(
                f"tracking is enabled and no MLflow server answers at {uri} ({error}). "
                "Start it, or set DOSSIER_MLFLOW_ENABLED=false."
            ) from None
        if not answered.is_success:
            raise TrackingUnavailable(
                f"tracking is enabled and the MLflow server at {uri} answered "
                f"{answered.status_code} {answered.reason_phrase} to {health}."
            )
    return MlflowTracker(uri)


class MlflowTracker:
    """The `Tracker` port, sent to an MLflow tracking server with `MlflowClient`.

    MLflow's own run, trace and span ids are kept here and never handed back:
    the port returns nothing, which is what keeps a record from becoming an
    input to a run (R0.10, R10.4).
    """

    def __init__(self, uri: str) -> None:
        import mlflow
        from mlflow import MlflowClient

        # Both of MLflow's paths, pointed at the one server dossier was given
        # (R10.9). A run is written through this client; a trace is exported by
        # MLflow's own asynchronous exporter, which reads the library's
        # process-wide configuration and not this client -- so without this line
        # every trace goes to MLflow's default local store, where the experiment
        # this client just created does not exist, and is dropped with a warning
        # while the run records perfectly. R11.1 and R11.2 are silently empty.
        #
        # Set from dossier's own configuration, never read from MLflow's
        # environment: a `MLFLOW_TRACKING_URI` left over from another project
        # decides nothing here (R10.1).
        mlflow.set_tracking_uri(uri)
        self._client = MlflowClient(tracking_uri=uri)
        self._experiment_id: str | None = None
        self._run_id: str | None = None
        self._trace_id: str | None = None
        self._root_span_id: str | None = None

    def start_run(self, *, experiment: str, name: str, tags: Mapping[str, str]) -> None:
        found = self._client.get_experiment_by_name(experiment)
        self._experiment_id = (
            found.experiment_id
            if found is not None
            else self._client.create_experiment(experiment)
        )
        run = self._client.create_run(self._experiment_id, tags=dict(tags), run_name=name)
        self._run_id = run.info.run_id

    def log_params(self, params: Mapping[str, str]) -> None:
        from mlflow.entities import Param

        self._client.log_batch(
            self._run_id, params=[Param(key, str(value)) for key, value in params.items()]
        )

    def log_metrics(self, metrics: Mapping[str, float]) -> None:
        from mlflow.entities import Metric

        # MLflow timestamps every metric. It is a record of when, never an
        # input: nothing here reaches a key or a manifest (R10.4).
        now = int(time.time() * 1000)
        self._client.log_batch(
            self._run_id,
            metrics=[Metric(key, float(value), now, 0) for key, value in metrics.items()],
        )

    def log_artifact(self, name: str, content: bytes) -> None:
        self._client.log_text(self._run_id, content.decode("utf-8"), name)

    def start_trace(self, *, name: str, tags: Mapping[str, str]) -> None:
        root = self._client.start_trace(
            name=name,
            tags=dict(tags),
            experiment_id=self._experiment_id,
            run_id=self._run_id,
        )
        self._trace_id, self._root_span_id = root.trace_id, root.span_id

    def span(self, *, kind: str, name: str, attributes: Mapping[str, object]) -> None:
        child = self._client.start_span(
            name=name,
            trace_id=self._trace_id,
            parent_id=self._root_span_id,
            span_type=kind.upper(),
            attributes=dict(attributes),
        )
        self._client.end_span(self._trace_id, child.span_id)

    def end_trace(self, *, status: str, error: str | None = None) -> None:
        self._client.end_trace(
            self._trace_id,
            attributes={"error": error} if error else None,
            status=status,
        )
        self._trace_id = self._root_span_id = None

    def end_run(self, *, status: str) -> None:
        self._client.set_terminated(self._run_id, status=status)
