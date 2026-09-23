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
from dossier.domain.ports import (
    DatasetRegistry,
    PromptRegistry,
    Tracker,
    VersionRegistry,
)
from dossier.domain.prompts import PublishedPrompt
from dossier.domain.versions import (
    HASH_TAG,
    MODEL_TYPE,
    PublishedVersion,
    VersionRecord,
)

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
        # Verdicts waiting for their trace to reach the server. See `assess`.
        self._pending: list[dict[str, str | bool]] = []

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

    def describe(self, text: str) -> None:
        """Set `mlflow.note.content`, the tag MLflow's UI renders as Description.

        A tag rather than a field: MLflow has no description column on a run, and
        this is the one name its UI reads (R10.12).
        """
        self._client.set_tag(self._run_id, "mlflow.note.content", text)

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

    def rendered_prompt(self, *, name: str, version: int) -> None:
        """Link this run to the prompt version it rendered (R14.7).

        `link_prompt_version_to_run` is MLflow's own edge for this, so the
        prompt's page lists the runs that used it and the run's page lists the
        prompts -- which is the whole point of having published them.

        The run id comes from the run this tracker already holds. dossier never
        activates a run (R10.4), so there is no ambient one to infer.
        """
        # MLflow addresses a version by URI here. The same scheme is what
        # `load_prompt` would fetch through, and this is deliberately not that
        # call: nothing comes back but `None`, and no template crosses into the
        # run (R14.5).
        self._client.link_prompt_version_to_run(
            run_id=self._run_id, prompt=f"prompts:/{name}/{version}"
        )

    def produced_version(self, version_id: str) -> None:
        """Link this run to the version it built, as one of its outputs (R13.2).

        `log_outputs` rather than the registry's `source_run_id`: a live spike
        found that `source_run_id` fills the *model's* source field and leaves
        the run's own model column empty, and the run's column is the one this
        spec exists to fill. `step=0` because dossier registers one version per
        run and MLflow wants an ordinal.
        """
        from mlflow.entities import LoggedModelOutput

        self._client.log_outputs(self._run_id, models=[LoggedModelOutput(version_id, 0)])

    def scored_version(self, version_id: str) -> None:
        """Link this run to the version it measured, as one of its inputs (R13.2)."""
        from mlflow.entities import LoggedModelInput

        self._client.log_inputs(self._run_id, models=[LoggedModelInput(version_id)])

    def version_prompt(self, *, version_id: str, name: str, version: int) -> None:
        """Link the pipeline version to a prompt version it is made of (R14.12).

        `link_prompt_version_to_model` keeps a logged model's prompts in one
        `mlflow.linkedPrompts` tag, and a live spike confirmed a second link of
        the same version leaves one entry -- so a run of a version already
        linked sends a link that changes nothing, and a run completing one
        after a late publish adds only what is new. A model the server cannot
        find raises RESOURCE_DOES_NOT_EXIST, which `BestEffortTracker` turns
        into a lost link rather than a lost run.
        """
        self._client.link_prompt_version_to_model(
            name=name, version=str(version), model_id=version_id
        )

    def log_version_metrics(self, *, version_id: str, metrics: Mapping[str, float]) -> None:
        """Record figures against the version as well as against this run (R13.3).

        Through `log_metric` with `model_id`, which a live spike confirmed
        accumulates across runs with each value carrying the run it came from --
        so a version scored twice shows both measurements rather than the later
        one silently replacing the earlier.
        """
        run_id = self._run_id
        for name, value in metrics.items():
            self._client.log_metric(run_id, name, value, model_id=version_id)

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

    def assess(self, *, name: str, value: bool, rationale: str, source: str) -> None:
        """Hold the verdict until its trace is on the server, then attach it (R11.16).

        Held rather than sent, and this is the whole of why: a trace is exported
        by MLflow's **asynchronous** exporter, so at the moment a span is being
        recorded the trace does not exist on the server yet. Sending the feedback
        here answers `RESOURCE_DOES_NOT_EXIST: Trace with ID ... not found`, which
        is what a live run against a real server does and what no fake can show --
        the same asynchrony R10.9 was written about, biting a second time.

        `end_trace` flushes the exporter and sends what is held.
        """
        self._pending.append(
            {"name": name, "value": value, "rationale": rationale, "source": source}
        )

    def end_trace(self, *, status: str, error: str | None = None) -> None:
        import mlflow
        from mlflow.entities.assessment_source import AssessmentSource, AssessmentSourceType

        trace_id = self._trace_id
        self._client.end_trace(
            trace_id,
            attributes={"error": error} if error else None,
            status=status,
        )
        if self._pending:
            # The exporter is asynchronous; feedback on a trace it has not sent
            # yet is refused. Flushed here rather than at the end of the run, so
            # the wait is one trace's worth and a verdict is on its trace before
            # anything else is recorded.
            mlflow.flush_trace_async_logging()
            for verdict in self._pending:
                # The returned `Assessment` is dropped: the port sends and
                # returns nothing, and an id read back from a server is the first
                # way for a record to become an input (R0.10).
                mlflow.log_feedback(
                    trace_id=trace_id,
                    name=str(verdict["name"]),
                    value=verdict["value"],
                    rationale=str(verdict["rationale"]) or None,
                    source=AssessmentSource(
                        source_type=AssessmentSourceType.LLM_JUDGE,
                        source_id=str(verdict["source"]),
                    ),
                )
            self._pending = []
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
        if not answered.is_success:
            # Any answer that is not a success, not only a 404. A file-backed
            # server does not 404 here -- it reaches the handler and fails
            # inside it, answering 500 -- and a check that looked only for 404
            # let the publish through to hang on MLflow's own retry of the 500.
            raise TrackingUnavailable(
                f"the MLflow server at {uri} cannot hold an evaluation dataset: "
                f"{DATASETS_ENDPOINT} answered {answered.status_code} "
                f"{answered.reason_phrase}. Datasets need a SQL backend -- start the "
                "server with --backend-store-uri (postgresql, mysql, sqlite or "
                "mssql), not a file store."
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


class MlflowPromptRegistry:
    """The `PromptRegistry` port, over `mlflow.genai.register_prompt` and the
    model registry's version search (spec 014).

    The one read this port permits is `latest` -- it decides a **write**
    (whether to publish at all), and reaches no run, key or file (R14.5 row 4).
    """

    def __init__(self, uri: str) -> None:
        import mlflow

        mlflow.set_tracking_uri(uri)
        self._uri = uri

    def publish(
        self,
        *,
        name: str,
        template: str,
        tags: Mapping[str, str],
        commit_message: str = "",
    ) -> PublishedPrompt:
        import mlflow

        version = mlflow.genai.register_prompt(
            name=name,
            template=template,
            commit_message=commit_message,
            tags=dict(tags),
        )
        return PublishedPrompt(
            name=version.name,
            version=int(version.version),
            prompt_hash=dict(version.tags or {}).get("dossier.prompt_hash", ""),
            created=True,
        )

    def latest(self, name: str) -> PublishedPrompt | None:
        from mlflow import MlflowClient
        from mlflow.exceptions import MlflowException

        client = MlflowClient(tracking_uri=self._uri)
        try:
            versions = client.search_prompt_versions(name)
        except MlflowException as error:
            if error.error_code == "RESOURCE_DOES_NOT_EXIST":
                return None
            raise
        if not versions:
            return None

        newest = max(versions, key=lambda version: version.version)
        return PublishedPrompt(
            name=newest.name,
            version=int(newest.version),
            prompt_hash=dict(newest.tags or {}).get("dossier.prompt_hash", ""),
            created=False,
        )

    def find(self, name: str, prompt_hash: str) -> PublishedPrompt | None:
        """The version of `name` tagged with `prompt_hash`, oldest first (R14.7).

        Searched by tag rather than taken from the top of the history, because a
        run links what it *rendered*: a prompt edited and republished since would
        otherwise attach its newest words to a run that never saw them.

        Oldest first because a hash reverted to is the same hash. Republishing a
        prompt back to text it already held leaves two versions tagged
        identically, and the first is the one a person reading the history would
        call the original.
        """
        from mlflow import MlflowClient
        from mlflow.exceptions import MlflowException

        client = MlflowClient(tracking_uri=self._uri)
        try:
            versions = client.search_prompt_versions(name)
        except MlflowException as error:
            if error.error_code == "RESOURCE_DOES_NOT_EXIST":
                return None
            raise

        for version in sorted(versions, key=lambda held: int(held.version)):
            if dict(version.tags or {}).get("dossier.prompt_hash") == prompt_hash:
                return PublishedPrompt(
                    name=version.name,
                    version=int(version.version),
                    prompt_hash=prompt_hash,
                    created=False,
                )
        return None


# What a FileStore-backed server has no endpoint for. A prompt is a registered
# model version underneath, and the model registry is a component a FileStore
# does not implement at all -- every one of its endpoints 404s, search
# included -- while a SQL-backed server answers.
PROMPTS_ENDPOINT = "/api/2.0/mlflow/registered-models/search"


def connect_prompts(uri: str, *, verify: bool = True) -> PromptRegistry:
    """A prompt registry recording to `uri`, or `TrackingUnavailable` saying why not.

    Three checks, in the order a person would fix them: the `tracking` extra, a
    server that answers, and a server whose store can hold a prompt at all
    (R14.6). The third is this function's reason for existing beside `connect`:
    a prompt version is a registered model version, and a FileStore-backed
    server has no model registry behind it, so a person publishing to one is
    told which server setting to change rather than handed an MLflow
    traceback.
    """
    # `verify=False` on the run path (R14.7): the tracker has already
    # connected to this same server, so a second probe buys nothing and
    # costs a round-trip on a command that never made one. R10.4 is that
    # tracking changes nothing about a run, and a startup probe is a change.
    if verify:
        connect(uri)  # the extra and the server, refused with their own messages

    if verify and uri.startswith(("http://", "https://")):
        search = uri.rstrip("/") + PROMPTS_ENDPOINT
        try:
            with httpx.Client(
                transport=HEALTH_TRANSPORT, timeout=HEALTH_TIMEOUT_SECONDS
            ) as http:
                answered = http.get(search, params={"max_results": 1})
        except httpx.HTTPError as error:
            raise TrackingUnavailable(
                f"tracking is enabled and no MLflow server answers at {uri} ({error}). "
                "Start it, or set DOSSIER_MLFLOW_ENABLED=false."
            ) from None
        if not answered.is_success:
            # Any answer that is not a success, not only a 404. A file-backed
            # server does not 404 here -- it reaches the handler and fails
            # inside it, answering 500 -- and a check that looked only for 404
            # let the publish through to hang on MLflow's own retry of the 500.
            raise TrackingUnavailable(
                f"the MLflow server at {uri} cannot hold a prompt registry: "
                f"{PROMPTS_ENDPOINT} answered {answered.status_code} "
                f"{answered.reason_phrase}. A prompt registry needs a SQL backend -- "
                "start the server with --backend-store-uri (postgresql, mysql, "
                "sqlite or mssql), not a file store."
            )
    return MlflowPromptRegistry(uri)


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


def connect_versions(uri: str) -> VersionRegistry:
    """A version registry recording to `uri` (spec 013).

    Only `connect`'s checks -- the extra and a server that answers. No check
    that the store can hold a logged model, and deliberately not: a dataset
    publish exists only to make the record and is refused when it cannot (R12.5),
    while a version is registered during `dossier run`, which has work to do
    either way. A store that cannot hold one fails at `register` and is swallowed
    by the best-effort wrapper, which says so at the end (R13.5).
    """
    connect(uri)
    return MlflowVersionRegistry(uri)


class MlflowVersionRegistry:
    """The `VersionRegistry` port, over MLflow's logged models.

    The second thing in `dossier` that reads an id back from a tracking server.
    It may reach a tag, the link `Tracker` records and a terminal line, and
    nothing else, which is the caller's obligation and stated at the port
    (R13.4).
    """

    def __init__(self, uri: str) -> None:
        import mlflow

        self._uri = uri
        self._client = mlflow.MlflowClient(tracking_uri=uri)

    def register(self, *, record: VersionRecord, experiment: str) -> PublishedVersion:
        """Find this version by its identifying pair, or create it ready (R13.1)."""
        experiment_id = self._experiment_id(experiment)
        found = self._find(record, experiment_id)
        if found is not None:
            return PublishedVersion(
                version_id=found.model_id,
                name=found.name,
                pipeline_hash=record.tags[HASH_TAG],
                created=False,
                params=dict(found.params or {}),
            )
        made = self._client.create_logged_model(
            experiment_id=experiment_id,
            name=record.name,
            model_type=MODEL_TYPE,
            params=dict(record.params),
            tags=dict(record.tags),
        )
        # A model left pending reads as something still being written, which is
        # untrue the moment the run that produced it has ended (R13.1).
        self._client.finalize_logged_model(made.model_id, "READY")
        return PublishedVersion(
            version_id=made.model_id,
            name=made.name,
            pipeline_hash=record.tags[HASH_TAG],
            created=True,
            params=dict(record.params),
        )

    def _experiment_id(self, experiment: str) -> str:
        found = self._client.get_experiment_by_name(experiment)
        return found.experiment_id if found else self._client.create_experiment(experiment)

    def _find(self, record: VersionRecord, experiment_id: str):
        """The one logged model this pair names, or `None`.

        The conjunction, never either half. A live spike found that the name
        alone matched every version of the pipeline and the hash alone matched
        every pipeline that resolved to it; only both together returned one
        (R13.1 rows 4-5). Matching on one would hand one pipeline's accuracy to
        another.
        """
        version = record.tags[HASH_TAG]
        hits = self._client.search_logged_models(
            experiment_ids=[experiment_id],
            filter_string=(f"name = '{record.name}' AND params.version_hash = '{version}'"),
            max_results=1,
        )
        return hits[0] if hits else None
