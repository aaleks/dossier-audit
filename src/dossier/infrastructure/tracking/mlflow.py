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
from collections.abc import Mapping, Sequence

import httpx

from dossier.domain.datasets import PublishedDataset
from dossier.domain.ports import DatasetRegistry, Tracker

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

    def log_dataset(self, *, name: str, dataset_id: str, digest: str) -> None:
        """Log the dataset as an input of this run (R11.7).

        `EvaluationDataset` subclasses `mlflow.data.dataset.Dataset`, so the run
        carries it where the UI shows a run's inputs -- which is the whole point
        of the link: the answers a figure was measured against are a click away
        rather than a hash lookup.
        """
        from mlflow.entities import DatasetInput, InputTag
        from mlflow.genai.datasets import get_dataset

        # Converted the way MLflow's own `log_input` converts it -- see
        # `_create_dataset_input` in `mlflow/tracking/fluent.py`, which is
        # `DatasetInput(dataset=dataset._to_mlflow_entity(), tags=...)`. The
        # fluent function itself logs to whatever run is *active*, and this
        # tracker holds its run by id rather than activating one, so it cannot be
        # used. Handing `log_inputs` the dataset itself raises TypeError: it
        # wants a `DatasetInput`, and an `EvaluationDataset` is a `Dataset`.
        held = get_dataset(dataset_id=dataset_id)
        self._client.log_inputs(
            self._run_id,
            datasets=[
                DatasetInput(
                    dataset=held._to_mlflow_entity(),
                    # How the dataset was used, which is what MLflow's UI groups
                    # a run's inputs by.
                    tags=[InputTag(key="mlflow.data.context", value="eval")],
                )
            ],
        )

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


# What a FileStore-backed server has no endpoint for. Evaluation datasets live in
# tables, so a server started without `--backend-store-uri` on a SQL database
# cannot hold one, and says so with a 404 rather than an error a person can read.
DATASETS_ENDPOINT = "/api/3.0/mlflow/datasets/search"


def connect_datasets(uri: str) -> DatasetRegistry:
    """A dataset registry recording to `uri`, or `TrackingUnavailable` saying why not.

    Three checks, in the order a person would fix them: the `tracking` extra, a
    server that answers, and a server whose store can hold a dataset at all
    (R12.5). The third is this function's reason for existing beside `connect`:
    every other record `dossier` sends works against a FileStore, and a dataset
    does not, so a person publishing to one is told which server setting to
    change rather than handed an MLflow traceback.
    """
    connect(uri)  # the extra and the server, refused with their own messages

    if uri.startswith(("http://", "https://")):
        search = uri.rstrip("/") + DATASETS_ENDPOINT
        try:
            with httpx.Client(
                transport=HEALTH_TRANSPORT, timeout=HEALTH_TIMEOUT_SECONDS
            ) as http:
                answered = http.post(search, json={"max_results": 1})
        except httpx.HTTPError as error:
            raise TrackingUnavailable(
                f"tracking is enabled and no MLflow server answers at {uri} ({error}). "
                "Start it, or set DOSSIER_MLFLOW_ENABLED=false."
            ) from None
        if answered.status_code == 404:
            raise TrackingUnavailable(
                f"the MLflow server at {uri} cannot hold an evaluation dataset: "
                f"{DATASETS_ENDPOINT} is not there. Datasets need a SQL backend -- "
                "start the server with --backend-store-uri (postgresql, mysql, "
                "sqlite or mssql), not a file store."
            )
    return MlflowDatasetRegistry(uri)


class MlflowDatasetRegistry:
    """The `DatasetRegistry` port, over `mlflow.genai.datasets`.

    The one thing in `dossier` that reads an id back from a tracking server. It
    may reach a tag and a terminal line and nothing else, which is the caller's
    obligation and stated at the port (R12.4).
    """

    def __init__(self, uri: str) -> None:
        import mlflow

        mlflow.set_tracking_uri(uri)
        self._uri = uri

    def publish(
        self,
        *,
        name: str,
        experiment: str,
        records: Sequence[Mapping[str, object]],
        tags: Mapping[str, str],
    ) -> PublishedDataset:
        import mlflow
        from mlflow.exceptions import MlflowException
        from mlflow.genai.datasets import (
            add_dataset_to_experiments,
            create_dataset,
            get_dataset,
            set_dataset_tags,
        )

        experiment_id = mlflow.set_experiment(experiment).experiment_id

        created = False
        try:
            dataset = get_dataset(name=name)
        except MlflowException:
            # Not there yet. Created rather than looked up again, and the id of
            # the experiment it belongs to is the one just resolved -- so the
            # dataset lands beside the runs measured against it (R12.1).
            dataset = create_dataset(name=name, experiment_id=[experiment_id], tags=dict(tags))
            created = True

        if not created:
            # One gold set is one dataset, whatever number of pipelines measure
            # themselves against it: the experiment joins the ones it already
            # belongs to instead of a second dataset appearing (R12.6).
            if experiment_id not in (dataset.experiment_ids or []):
                add_dataset_to_experiments(
                    dataset_id=dataset.dataset_id, experiment_ids=[experiment_id]
                )
            held = dict(dataset.tags or {})
            if any(held.get(key) != value for key, value in tags.items()):
                set_dataset_tags(dataset_id=dataset.dataset_id, tags=dict(tags))

        before = _record_count(dataset)
        if records:
            # Skipped for a gold set that has not moved, because a merge is a
            # write and MLflow's digest moves on a write whether or not anything
            # changed (R12.3). `publish_gold` decides; this only obeys.
            dataset.merge_records(list(records))
        refreshed = get_dataset(dataset_id=dataset.dataset_id)
        after = _record_count(refreshed)

        return PublishedDataset(
            dataset_id=refreshed.dataset_id,
            name=name,
            digest=refreshed.digest,
            records=after,
            added=max(after - before, 0),
            created=created,
            tags=dict(refreshed.tags or tags),
        )

    def find(self, name: str) -> PublishedDataset | None:
        from mlflow.exceptions import MlflowException
        from mlflow.genai.datasets import get_dataset

        try:
            dataset = get_dataset(name=name)
        except MlflowException:
            return None
        return PublishedDataset(
            dataset_id=dataset.dataset_id,
            name=name,
            digest=dataset.digest,
            records=_record_count(dataset),
            added=0,
            created=False,
            tags=dict(dataset.tags or {}),
        )


def _record_count(dataset) -> int:
    """How many records a dataset holds, from the profile MLflow keeps beside it.

    Read from the profile rather than by loading every record: a gold set is
    small, but a count is all that is wanted and `to_df()` would fetch the
    answers back to arrive at it.
    """
    import json

    profile = dataset.profile
    if isinstance(profile, str):
        profile = json.loads(profile or "{}")
    return int((profile or {}).get("num_records", 0))
