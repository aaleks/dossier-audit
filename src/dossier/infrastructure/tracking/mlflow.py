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

import ssl
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from dossier.domain.datasets import PublishedDataset
from dossier.domain.ports import (
    DatasetRegistry,
    PromptRegistry,
    ReviewSource,
    Tracker,
    VersionRegistry,
)
from dossier.domain.prompts import PublishedPrompt
from dossier.domain.review import Verdict
from dossier.domain.tracking import CA_BUNDLE, MlflowAuth, refused_credential
from dossier.domain.versions import (
    HASH_TAG,
    MODEL_TYPE,
    PublishedVersion,
    VersionRecord,
)
from dossier.infrastructure.tracking.auth import PROVIDER, configure, configured, headers
from dossier.infrastructure.tracking.oidc import TokenRefused, TokenSource, unverified

# How the startup check reaches the server. `None` is a real connection; a test
# answers with an `httpx.MockTransport`, so no socket is opened (R0.10).
HEALTH_TRANSPORT: httpx.BaseTransport | None = None

# Long enough for a server under load to answer a health check, short enough
# that a wrong URI is reported before anyone wonders why nothing happened.
HEALTH_TIMEOUT_SECONDS = 5.0

# The one read the startup check makes with the credential (R10.18). MLflow's
# own basic auth leaves `/health` open -- a live server answered 200 there and
# 401 here to the same anonymous client -- so `/health` alone passed a credential
# every later record would be refused. A read, because a check that wrote would
# leave something behind; and so it cannot prove write access, which R10.22 is for.
CREDENTIAL_ENDPOINT = "/api/2.0/mlflow/experiments/search"


class TrackingUnavailable(RuntimeError):
    """Tracking is switched on, and nothing can be recorded -- said before any work."""


def connect(
    uri: str, *, auth: MlflowAuth | None = None, ca_bundle: str | None = None
) -> Tracker:
    """A tracker recording to `uri`, or `TrackingUnavailable` saying why not (R10.5).

    Three checks, in the order a person would fix them: the `tracking` extra is
    installed, a server answers at an `http(s)` URI, and it accepts the
    credential (R10.18). A local store such as `sqlite:///mlflow.db` has no
    server to ask, so it is not asked.

    Before any request, `auth` is made the credential every request to the
    server carries -- this check's, and every one MLflow sends after it (R10.17).
    """
    try:
        import mlflow  # noqa: F401 -- the extra is what is being checked for
    except ImportError as error:
        raise TrackingUnavailable(
            "tracking is enabled and `mlflow` is not installed. Install the extra -- "
            "pip install 'dossier[tracking]' -- or set DOSSIER_MLFLOW_ENABLED=false."
        ) from error

    auth = auth or MlflowAuth()
    verify = _trust(uri, auth, ca_bundle)
    _configure(uri, auth, verify)
    if uri.startswith(("http://", "https://")):
        health = uri.rstrip("/") + "/health"
        read = uri.rstrip("/") + CREDENTIAL_ENDPOINT
        try:
            with httpx.Client(
                transport=HEALTH_TRANSPORT, timeout=HEALTH_TIMEOUT_SECONDS, verify=verify
            ) as http:
                for asked, params in ((health, None), (read, {"max_results": 1})):
                    _accepted(
                        uri, asked, http.get(asked, params=params, headers=headers()), auth
                    )
        except httpx.HTTPError as error:
            if unverified(error):
                # A server that answered with a certificate nobody here trusts is
                # running; sending a person to start it would be the wrong fix.
                raise TrackingUnavailable(
                    f"tracking is enabled and the certificate of the MLflow server at "
                    f"{uri} could not be verified ({error}). A server signed by a "
                    f"private CA is trusted by naming that CA in {CA_BUNDLE}."
                ) from None
            raise TrackingUnavailable(
                f"tracking is enabled and no MLflow server answers at {uri} ({error}). "
                "Start it, or set DOSSIER_MLFLOW_ENABLED=false."
            ) from None
    return MlflowTracker(uri)


def _trust(uri: str, auth: MlflowAuth, ca_bundle: str | None) -> ssl.SSLContext | bool:
    """What every TLS connection to MLflow and its identity provider trusts (R10.20).

    The system's store unless `ca_bundle` names a CA, in which case that CA and
    nothing else: the startup check and the token exchange are handed it, and
    MLflow is told its path through its own setting. A connection with no TLS
    reads no bundle, so a wrong path on a laptop's `http://localhost:5000` is
    not refused. A relative path is resolved against the working directory, as
    `.env` is. There is no setting that turns verification off.
    """
    tls = uri.startswith("https://") or (auth.token_url or "").startswith("https://")
    if ca_bundle is None or not tls:
        return True
    path = Path(ca_bundle).resolve()
    if not path.is_file():
        raise TrackingUnavailable(
            f"{CA_BUNDLE} is {ca_bundle!r}, and there is no file at {path}."
        )
    try:
        context = ssl.create_default_context(cafile=str(path))
    except (ssl.SSLError, ValueError) as error:
        raise TrackingUnavailable(
            f"{CA_BUNDLE} is {ca_bundle!r}, which is not a PEM-encoded CA certificate "
            f"({error})."
        ) from None
    from mlflow.environment_variables import MLFLOW_TRACKING_SERVER_CERT_PATH

    MLFLOW_TRACKING_SERVER_CERT_PATH.set(str(path))
    return context


def _accepted(uri: str, asked: str, answered: httpx.Response, auth: MlflowAuth) -> None:
    """Refuse, before any work, an answer that is not a success -- saying which kind (R10.18).

    A refusal and a redirect are about the credential, and say so: a proxy in
    front of MLflow answers an unauthenticated request with its identity
    provider's login page, which a command cannot follow. Neither is "no server
    answers", which would send a person to restart a server that is running.
    """
    status = f"{answered.status_code} {answered.reason_phrase}"
    if answered.status_code in (401, 403):
        raise TrackingUnavailable(
            f"tracking is enabled and the MLflow server at {uri} answered {status} to "
            f"{asked}: {refused_credential(auth)}."
        )
    if answered.is_redirect:
        location = answered.headers.get("Location", "an address it did not give")
        raise TrackingUnavailable(
            f"tracking is enabled and the MLflow server at {uri} answered {status} to "
            f"{asked}, redirecting to {location} -- a login page a command cannot "
            f"follow: {refused_credential(auth)}. Behind a proxy, the proxy has to "
            "accept the credential itself (oauth2-proxy: --skip-jwt-bearer-tokens)."
        )
    if not answered.is_success:
        raise TrackingUnavailable(
            f"tracking is enabled and the MLflow server at {uri} answered {status} to {asked}."
        )


def _configure(uri: str, auth: MlflowAuth, verify: ssl.SSLContext | bool = True) -> None:
    """Ready MLflow for the server at `uri`, or refuse before any work.

    Two settings, both MLflow's own and both set through its API, as the tracking
    URI is (R10.9). `auth` becomes what every request carries (R10.17). And MLflow
    is told to print nothing (R10.23): `set_terminated` writes an emoji to
    standard output *before* it sends the update that closes a run, and where
    standard output is `cp1252` -- Windows, redirected -- the print raised, the
    update was never sent, and the run stayed `RUNNING` behind a clean exit 0.

    A local store is reached by no request and prints no link, so neither applies.
    """
    if not uri.startswith(("http://", "https://")):
        return
    from mlflow.environment_variables import MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT

    MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT.set(True)
    from mlflow.tracking.request_auth.registry import fetch_auth

    # MLflow finds providers through package metadata. An install older than the
    # entry point would leave every request with no credential while the startup
    # check below -- which takes its header from dossier directly -- passed.
    if fetch_auth(PROVIDER) is None:
        raise TrackingUnavailable(
            "MLflow cannot find dossier's request auth provider, so no credential would "
            "reach the server. The installed metadata predates it: reinstall dossier "
            "(pip install -e '.[tracking]', or uv sync) so its entry points are registered."
        )
    if configured(auth):
        return
    token = None
    if auth.mode == "oidc":
        # The first exchange, before the startup check and before any work
        # (R10.19): an identity provider that refuses the client, or is not
        # there, stops the command here, with MLflow asked nothing.
        source = TokenSource(auth, verify=verify)
        try:
            source.authorization()
        except TokenRefused as error:
            raise TrackingUnavailable(f"tracking is enabled and {error}") from None
        token = source.authorization
    configure(auth, token=token)


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
        # The trace each thread has open -- its id, its root span, and the
        # verdicts waiting for it to reach the server (see `assess`). A trace is
        # current in the thread that opened it, so a run's workers each record
        # into their own document's trace (R11.21).
        self._this = threading.local()
        self._opening = threading.Lock()
        # Every trace this run opened, in order, so each can be looked for on the
        # server as the record closes (R10.24). `None` for one MLflow could not
        # open, which is in no server's holdings.
        self._opened: list[str | None] = []
        # The places, among `_opened`, of the traces the server turned out not to
        # hold. Places rather than ids: the port reads no id back from a server,
        # so nothing MLflow holds can become an input (R0.10). Read by
        # `BestEffortTracker`, which does the counting.
        self.unrecorded_traces: frozenset[int] = frozenset()

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

    def start_trace(
        self,
        *,
        name: str,
        tags: Mapping[str, str],
        inputs: Mapping[str, object] | None = None,
    ) -> None:
        # The place is taken before MLflow is asked, so a trace it could not open
        # still has one. `BestEffortTracker` counts places, and one skipped here
        # would name every later trace by its neighbour's (R10.24 row 4). Taken
        # under a lock and kept, since another worker may open one meanwhile.
        with self._opening:
            place = len(self._opened)
            self._opened.append(None)
        root = self._client.start_trace(
            name=name,
            tags=dict(tags),
            experiment_id=self._experiment_id,
            run_id=self._run_id,
            # The trace list's Request column (R15.1). Only when there is one:
            # the judge's and a calibration's traces are opened as before.
            **({} if inputs is None else {"inputs": dict(inputs)}),
        )
        self._this.trace_id, self._this.root_span_id = root.trace_id, root.span_id
        self._this.pending = []
        self._opened[place] = root.trace_id

    def span(self, *, kind: str, name: str, attributes: Mapping[str, object]) -> None:
        child = self._client.start_span(
            name=name,
            trace_id=self._this.trace_id,
            parent_id=self._this.root_span_id,
            span_type=kind.upper(),
            attributes=dict(attributes),
        )
        self._client.end_span(self._this.trace_id, child.span_id)

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
        self._this.pending.append(
            {"name": name, "value": value, "rationale": rationale, "source": source}
        )

    def end_trace(
        self,
        *,
        status: str,
        error: str | None = None,
        outputs: object = None,
        tags: Mapping[str, str] | None = None,
    ) -> None:
        import mlflow
        from mlflow.entities.assessment_source import AssessmentSource, AssessmentSourceType

        trace_id = self._this.trace_id
        pending = self._this.pending
        # Before the trace ends, while MLflow holds it in memory: what puts it in
        # the review queue is known only once the answer is checked (R15.2).
        for key, value in (tags or {}).items():
            self._client.set_trace_tag(trace_id, key, value)
        self._client.end_trace(
            trace_id,
            attributes={"error": error} if error else None,
            status=status,
            # The trace list's Response column (R15.1), when there is one.
            **({} if outputs is None else {"outputs": outputs}),
        )
        if pending:
            # The exporter is asynchronous; feedback on a trace it has not sent
            # yet is refused. Flushed here rather than at the end of the run, so
            # the wait is one trace's worth and a verdict is on its trace before
            # anything else is recorded.
            mlflow.flush_trace_async_logging()
            for verdict in pending:
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
        self._this.trace_id = self._this.root_span_id = None
        self._this.pending = []

    def use_experiment(self, experiment: str) -> None:
        """Send the traces that follow to `experiment`, under no run (R11.35)."""
        found = self._client.get_experiment_by_name(experiment)
        self._experiment_id = (
            found.experiment_id
            if found is not None
            else self._client.create_experiment(experiment)
        )
        self._run_id = None

    def end_traces(self) -> None:
        """Look for every trace opened under no run, as `end_run` does for a run's (R10.24).

        The exporter is flushed first: it sends a trace after it ends, on a
        thread of its own, and a trace looked for before then is not there yet.
        """
        import mlflow

        if not self._opened:
            return
        mlflow.flush_trace_async_logging()
        held = set()
        for trace_id in self._opened:
            if trace_id is not None and self._client.get_trace(trace_id) is not None:
                held.add(trace_id)
        self.unrecorded_traces = frozenset(
            place for place, trace_id in enumerate(self._opened) if trace_id not in held
        )

    def end_run(self, *, status: str) -> None:
        """Look for every trace the run opened, then close it (R10.24).

        No trace call reaches the server: MLflow's exporter sends a trace after it
        ends, on a thread of its own, so a trace the server refused raises
        nowhere dossier could see and R10.6 counted none. Found live, with a
        READ-only account whose run said nothing while the server logged
        `POST /api/3.0/mlflow/traces 403`. So the exporter is flushed, and the
        run's traces are looked up by the run they belong to, without their
        spans: one request per hundred traces, not one per trace.
        """
        if self._opened:
            self.unrecorded_traces = self._unheld()
        self._client.set_terminated(self._run_id, status=status)

    def _unheld(self) -> frozenset[int]:
        """The places of the traces this run opened that the server does not hold."""
        import mlflow

        every = frozenset(range(len(self._opened)))
        if self._run_id is None:
            # The server refused the run, so no trace can belong to it and there
            # is nothing to look under (R10.24 row 2).
            return every
        try:
            mlflow.flush_trace_async_logging()
            found = self._client.search_traces(
                locations=[self._experiment_id],
                run_id=self._run_id,
                include_spans=False,
                max_results=len(self._opened),
            )
        except Exception:
            # A server that cannot be asked shows no trace held, so none counts
            # as recorded (row 5). Passed over here rather than raised to
            # `BestEffortTracker`, because the close after it must still be sent.
            return every
        held = {trace.info.trace_id for trace in found}
        return frozenset(
            place for place, trace_id in enumerate(self._opened) if trace_id not in held
        )


# What a FileStore-backed server has no endpoint for. Evaluation datasets live in
# tables, so a server started without `--backend-store-uri` on a SQL database
# cannot hold one, and says so with a 404 rather than an error a person can read.
DATASETS_ENDPOINT = "/api/3.0/mlflow/datasets/search"


def connect_datasets(
    uri: str, *, auth: MlflowAuth | None = None, ca_bundle: str | None = None
) -> DatasetRegistry:
    """A dataset registry recording to `uri`, or `TrackingUnavailable` saying why not.

    Three checks, in the order a person would fix them: the `tracking` extra, a
    server that answers, and a server whose store can hold a dataset at all
    (R12.5). The third is this function's reason for existing beside `connect`:
    every other record `dossier` sends works against a FileStore, and a dataset
    does not, so a person publishing to one is told which server setting to
    change rather than handed an MLflow traceback.
    """
    # The extra, the server and the credential, refused with their own messages.
    connect(uri, auth=auth, ca_bundle=ca_bundle)

    if uri.startswith(("http://", "https://")):
        search = uri.rstrip("/") + DATASETS_ENDPOINT
        try:
            with httpx.Client(
                transport=HEALTH_TRANSPORT,
                timeout=HEALTH_TIMEOUT_SECONDS,
                verify=_trust(uri, auth or MlflowAuth(), ca_bundle),
            ) as http:
                answered = http.post(search, json={"max_results": 1}, headers=headers())
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


def connect_prompts(
    uri: str,
    *,
    auth: MlflowAuth | None = None,
    ca_bundle: str | None = None,
    verify: bool = True,
) -> PromptRegistry:
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
    auth = auth or MlflowAuth()
    if verify:
        # The extra, the server and the credential, refused with their own messages.
        connect(uri, auth=auth, ca_bundle=ca_bundle)
    else:
        # No probe, and still the credential and the trust: no request goes out
        # without them (R10.17, R10.20).
        _configure(uri, auth, _trust(uri, auth, ca_bundle))

    if verify and uri.startswith(("http://", "https://")):
        search = uri.rstrip("/") + PROMPTS_ENDPOINT
        try:
            with httpx.Client(
                transport=HEALTH_TRANSPORT,
                timeout=HEALTH_TIMEOUT_SECONDS,
                verify=_trust(uri, auth, ca_bundle),
            ) as http:
                answered = http.get(search, params={"max_results": 1}, headers=headers())
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


def connect_versions(
    uri: str, *, auth: MlflowAuth | None = None, ca_bundle: str | None = None
) -> VersionRegistry:
    """A version registry recording to `uri` (spec 013).

    Only `connect`'s checks -- the extra and a server that answers. No check
    that the store can hold a logged model, and deliberately not: a dataset
    publish exists only to make the record and is refused when it cannot (R12.5),
    while a version is registered during `dossier run`, which has work to do
    either way. A store that cannot hold one fails at `register` and is swallowed
    by the best-effort wrapper, which says so at the end (R13.5).
    """
    connect(uri, auth=auth, ca_bundle=ca_bundle)
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


# How many traces one search asks for. Paged rather than capped: a pipeline
# reviewed for a year holds more traces than any one page, and a verdict left
# on the last of them is as much a verdict as one on the first.
REVIEW_PAGE = 100


def connect_reviews(
    uri: str, *, auth: MlflowAuth | None = None, ca_bundle: str | None = None
) -> ReviewSource:
    """A reader of reviewers' verdicts at `uri`, or `TrackingUnavailable` saying why not.

    The extra, the server and the credential are checked as for any record,
    before anything is read (R10.5, R15.3 row 6).
    """
    connect(uri, auth=auth, ca_bundle=ca_bundle)
    return MlflowReviewSource(uri)


class MlflowReviewSource:
    """Reviewers' verdicts, as MLflow holds them on a pipeline's traces (spec 015).

    An assessment is a reviewer's verdict when its source is `HUMAN`, it is still
    valid -- MLflow marks one another reviewer overrode as not -- and it sits on
    a trace a run wrote, one tagged with its step and document (spec 011). The
    judge's verdicts are `LLM_JUDGE` and are the judge's (R11.16).

    The author is `source_id` as MLflow holds it. The open-source trace view
    sends `User` for everyone, whoever is logged in, and the server stores what
    it is sent; that is reported as it is, never guessed at (spec 015).
    """

    def __init__(self, uri: str) -> None:
        import mlflow
        from mlflow import MlflowClient

        mlflow.set_tracking_uri(uri)
        self._client = MlflowClient(tracking_uri=uri)

    def human_verdicts(self, *, experiment: str) -> list[Verdict]:
        found = self._client.get_experiment_by_name(experiment)
        if found is None:
            # No run of this pipeline was ever recorded, so nothing was reviewed.
            return []
        verdicts: list[Verdict] = []
        runs: dict[str, str] = {}
        token: str | None = None
        while True:
            page = self._client.search_traces(
                locations=[found.experiment_id],
                include_spans=False,
                max_results=REVIEW_PAGE,
                page_token=token,
            )
            for trace in page:
                verdicts.extend(self._verdicts(trace.info, runs))
            token = getattr(page, "token", None)
            if not token:
                return verdicts

    def _verdicts(self, info, runs: dict[str, str]) -> list[Verdict]:
        step = info.tags.get("dossier.step")
        document = info.tags.get("dossier.document")
        if not step or not document:
            return []
        source_run = (info.request_metadata or {}).get("mlflow.sourceRun", "")
        if source_run and source_run not in runs:
            # The dossier run id is the MLflow run's name (R11.1): asked once per
            # run, however many traces it wrote.
            runs[source_run] = self._client.get_run(source_run).info.run_name
        read: list[Verdict] = []
        for assessment in info.assessments or []:
            if str(assessment.source.source_type) != "HUMAN":
                continue
            if getattr(assessment, "valid", None) is False:
                continue
            said = (
                assessment.feedback
                if assessment.feedback is not None
                else assessment.expectation
            )
            read.append(
                Verdict(
                    run=runs.get(source_run, ""),
                    step=step,
                    document=document,
                    name=assessment.name,
                    kind="feedback" if assessment.feedback is not None else "expectation",
                    value=said.value,
                    rationale=assessment.rationale or None,
                    reviewer=assessment.source.source_id,
                    at=datetime.fromtimestamp(assessment.create_time_ms / 1000, UTC).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    trace=info.trace_id,
                    assessment=assessment.assessment_id,
                )
            )
        return read
