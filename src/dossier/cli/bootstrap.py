"""What the commands are handed: the concrete things built from this machine.

The model client, the tracker and the registries each command reaches through,
built from this workspace's settings. Every builder here is a seam: a test
replaces `dossier.cli.bootstrap.build_model_client` with a `FakeModelClient`,
and a command reaches it as `bootstrap.build_model_client` so the replacement
is what it calls. `build_review_source` is not here: it is built by
`dossier review pull` alone, and lives beside it (R15.5).

Also what every command says alike: where a pipeline is, how a count reads,
which failures are a model's, and that another command holds the workspace.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import typer

from dossier.application.plan import latest_manifest
from dossier.config.endpoints import EndpointUnset, endpoint_for
from dossier.config.environment import environment
from dossier.config.load import ConfigError, load_converter_names
from dossier.domain.conversion import NoConverter, answering
from dossier.domain.install import stale_entry_points, stale_install_line
from dossier.domain.model_id import provider_of
from dossier.domain.ports import (
    DatasetRegistry,
    EmbeddingProvider,
    ImagePart,
    IndexSearch,
    IndexSink,
    ModelClient,
    PromptRegistry,
    Tracker,
    VersionRegistry,
)
from dossier.domain.resolution import ResolvedPlan
from dossier.domain.store import RUNS_ROOT, passed_over_line, stopped_line
from dossier.domain.tracking import TrackingSettings, experiment_name, name_template, namespace
from dossier.domain.tracking import capture as capture_setting
from dossier.domain.tracking import settings as tracking_settings
from dossier.infrastructure.converters.registry import installed_converters
from dossier.infrastructure.lock import WorkspaceHeld, WorkspaceLock
from dossier.infrastructure.models.openai_compatible import ModelRequestFailed
from dossier.infrastructure.models.registry import UnknownProvider, embedding_provider
from dossier.infrastructure.models.registry import provider as model_provider
from dossier.infrastructure.tracking.best_effort import (
    BestEffortTracker,
    BestEffortVersionRegistry,
)
from dossier.infrastructure.tracking.mlflow import (
    TrackingUnavailable,
    connect,
    connect_datasets,
    connect_prompts,
    connect_versions,
)

# A model failing, as a command meets it: nothing says where its provider is
# served (R9.2 row 3), no installed package provides it, or a request was
# refused or never answered after R9.17's retries (R9.12 row 4). Every command
# that asks a model says one in a line and exits 2, as `run` always has; anything
# else keeps the traceback that says where it happened (R9.25).
MODEL_FAILURES = (EndpointUnset, UnknownProvider, ModelRequestFailed)


def pipeline_path(workspace: Path, name: str) -> Path:
    path = workspace / "pipelines" / name / "pipeline.yaml"
    if not path.exists():
        # Naming where it looked matters more than naming what is missing: the
        # usual cause is being in the wrong directory (R2.12 example 3).
        raise ConfigError(f"no pipeline {name!r}: expected {path}")
    return path


def build_model_client(model_id: str) -> ModelClient:
    """Resolve a pinned model identifier to a client, reached where this machine says.

    The provider is the installed package the identifier names (R9.1). Where it
    is served comes from the environment, or from the provider's own default
    (R9.2), and is in no key -- so one identifier reached from two machines
    shares one cache.

    A named function rather than an inline construction: it is the seam the
    composition root hands to a use case, and R4.6 is the claim that `--plan`
    never reaches it. A test replaces this and asserts it was never called.
    """
    provider = provider_of(model_id)
    factory = model_provider(provider)
    endpoint = endpoint_for(
        provider,
        default_url=getattr(factory, "default_url", None),
        environ=environment(Path.cwd()),
    )
    return factory(model_id, url=endpoint.url, api_key=endpoint.api_key)


def build_embedding_provider(model_id: str) -> EmbeddingProvider:
    """Resolve a pinned embedding model to a client, reached where this machine says (R18.3).

    Built as a model client is: the provider is the installed package the
    identifier names, from the `dossier.embeddings` entry points, and its
    endpoint the one `DOSSIER_<PROVIDER>_URL` names, shared with that
    provider's chat client (R9.2). The seam a test replaces with a fake that
    counts what it is asked.
    """
    provider = provider_of(model_id)
    factory = embedding_provider(provider)
    endpoint = endpoint_for(
        provider,
        default_url=getattr(factory, "default_url", None),
        environ=environment(Path.cwd()),
    )
    return factory(model_id, url=endpoint.url, api_key=endpoint.api_key)


def build_index_sink(dsn: str) -> IndexSink:
    """The embedding index at `dsn`, reached only when it is first asked (R18.4).

    The driver is imported then, so a `dossier` installed without the `index`
    extra still runs every other command, and is told which extra to install
    when it is asked to write an index.
    """
    from dossier.infrastructure.index import connect

    return connect(dsn)


def build_index_search(dsn: str) -> IndexSearch:
    """The embedding index at `dsn`, to search, reached only when it is first asked (R19.12).

    As `build_index_sink`: the driver is imported then, so a `dossier`
    installed without the `index` extra is told which extra to install.
    """
    from dossier.infrastructure.index import connect_search

    return connect_search(dsn)


def build_tracker(settings: TrackingSettings) -> Tracker:
    """The tracker a command records to, checked before any work (R10.5).

    `connect` refuses, naming what to fix, when the `tracking` extra is missing
    or no server answers. A named function for the reason `build_model_client`
    is one: it is the seam the composition root hands to a use case, and a test
    replaces it with a `FakeTracker`.
    """
    return connect(settings.uri, auth=settings.auth, ca_bundle=settings.ca_bundle)


def tracking_for(
    workspace: Path, pipeline: str | None, *, kind: str, gold: str | None = None
) -> tuple[BestEffortTracker | None, str | None]:
    """The tracker and experiment a `dossier <kind>` records to, or `(None, None)`.

    Read and checked before any work: a typo in the switch or the template, the
    extra missing, or a server nobody can reach is refused now -- exit 2, naming
    what to fix -- rather than found after the work nobody can now inspect
    (R10.1, R10.2, R10.5).

    `gold` is the gold directory, and only `eval` has one. It defaults to `None`
    because sync, convert and run read no gold set: a template using `{gold}` is
    refused for them, naming the variable to fix (R10.2). Passing `None` from
    `eval` as well would refuse the one command that can actually fill it.
    """
    environ = environment(workspace)
    try:
        tracking = tracking_settings(environ)
        if tracking is None:
            return None, None
        experiment = experiment_name(kind=kind, pipeline=pipeline, gold=gold, environ=environ)
        # Resolved and discarded: the name is rendered later, when the command
        # holds the run id or the figures it carries, but a template naming a
        # placeholder this command cannot fill is refused here -- before any work
        # (R10.10 row 4), as the experiment's is.
        name_template(kind=kind, environ=environ)
        # With the rest of this machine's tracking settings, before any work
        # (R10.14): a prefix composed into a name only once a command was at
        # work reached `eval` and `calibrate` as a traceback, with their run
        # open (R14.10).
        namespace(environ)
        # A loss is said in the command's own terminal, once, as its record closes
        # (R10.21), and the first refusal as it happens, naming the credential's
        # variable (R10.22) -- by every command that records, because every one
        # builds its tracker here.
        return (
            BestEffortTracker(build_tracker(tracking), warn=_warn, auth=tracking.auth),
            experiment,
        )
    except (ValueError, TrackingUnavailable) as error:
        # Named by its pipeline, and by nothing for `gc`, which has none (R11.28).
        typer.echo(f"{pipeline}: {error}" if pipeline else str(error), err=True)
        raise typer.Exit(code=2) from error


def _warn(line: str) -> None:
    """A tracking warning, on standard error with every other warning dossier gives."""
    typer.echo(line, err=True)


def converters_for(workspace: Path) -> list:
    """The converters that answer in this workspace, as `sources.yaml` names them (R8.13).

    Every command that converts or pins converters asks here, so none of them can
    choose differently from the others. A name nothing installed carries stops
    the command before anything converts, as a declared pair nothing claims
    does (R8.24).
    """
    try:
        named = load_converter_names(workspace / "sources.yaml")
        return answering(installed_converters(), named=named)
    except (ConfigError, NoConverter) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error


def versions_for(workspace: Path) -> VersionRegistry | None:
    """The version registry for this workspace, or `None` when it cannot be built.

    `None` rather than raising. `tracking_for` has already refused a server
    nobody can reach (R10.5), so reaching here means tracking is on and
    answering; a registry that still cannot be built is a store that cannot hold
    a logged model, which costs the Models tab and not the run (R13.5).
    """
    settings = tracking_settings(environment(workspace))
    if settings is None:
        return None
    try:
        return build_version_registry(settings)
    except Exception:
        # Broadly, and on purpose. R13.5 is the promise that a run does not fail
        # because a Models tab cannot be filled, and *building* the registry is
        # as much a part of that as registering: it reaches the server, so it
        # can fail in as many ways. `BestEffortVersionRegistry` covers the
        # calls; this covers the construction. A tracker that could not be built
        # has already refused the command by here (R10.5), so nothing silently
        # lost is lost twice.
        return None


def capture_for(workspace: Path, pipeline: str) -> str:
    """What a span may carry on this machine: `full` text or only `hashes` (R10.8).

    Read only once tracking is on -- with nothing recording, the setting decides
    nothing -- and before any work, for the same reason the switch is: read as
    `full` a typo would copy text the person meant to keep out of the server,
    and finding that out after the run is finding it out after the copy.
    """
    try:
        return capture_setting(environment(workspace))
    except ValueError as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error


class BuiltOnFirstCall:
    """A model client that is not built until a stage first asks it something.

    A run served entirely from cache reaches no model, so it needs no endpoint
    and no client (R9.2 row 5, R0.17). Building one up front made a fully cached
    run fail on a machine that could have completed it. `model_id` is known
    without building anything: it is part of every key, and the keys are what
    decide whether a call happens at all.

    `build_model_client` is looked up when the first call is made rather than
    bound here, so the seam a test replaces is the one this reaches.
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._client: ModelClient | None = None
        # Several workers can miss at once (R9.19); the client is still built
        # once, and the others wait for it rather than building their own.
        self._building = threading.Lock()

    def complete(
        self, prompt: str, *, schema: dict | None = None, parts: Sequence[ImagePart] = ()
    ) -> str:
        if self._client is None:
            with self._building:
                if self._client is None:
                    self._client = build_model_client(self.model_id)
        return self._client.complete(prompt, schema=schema, parts=parts)


def count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def build_version_registry(settings: TrackingSettings) -> VersionRegistry:
    """The registry a pipeline version is registered through (spec 013).

    The seam a test replaces with a `FakeVersionRegistry`, as `build_tracker`
    and `build_dataset_registry` are. Wrapped best-effort here rather than at
    the call site, because `dossier run` has work to do whether or not MLflow
    can hold a logged model (R13.5).
    """
    return BestEffortVersionRegistry(
        connect_versions(settings.uri, auth=settings.auth, ca_bundle=settings.ca_bundle)
    )


def build_dataset_registry(settings: TrackingSettings) -> DatasetRegistry:
    """The registry a gold set is published through, checked before anything is sent.

    A named function for the reason `build_tracker` is one: it is the seam the
    composition root hands to a use case, and a test replaces it with a
    `FakeDatasetRegistry`. Separate from `build_tracker` because the two are
    different ports -- this one returns what it published, which a `Tracker`
    never does (R15.5 row 2), and which R0.17 lets tracking read back because
    spec 012 fences it.
    """
    return connect_datasets(settings.uri, auth=settings.auth, ca_bundle=settings.ca_bundle)


def prompt_registry_for(workspace: Path) -> PromptRegistry | None:
    """The registry a run asks which version carries the prompt it rendered.

    Best-effort in the sense `versions_for` is: a server that cannot be reached
    costs the link and never the run, because tracking may not change what a run
    does (R10.4, R14.7 row 2).
    """
    settings = tracking_settings(environment(workspace))
    if settings is None:
        return None
    try:
        # Through the seam, so a test replaces one function rather than two,
        # and unverified, so a run pays no probe for a capability only
        # `prompts publish` needs (R10.4).
        return build_prompt_registry(settings, verify=False)
    except TrackingUnavailable:
        return None


def build_prompt_registry(settings: TrackingSettings, *, verify: bool = True) -> PromptRegistry:
    """The registry a pipeline's prompts are published through.

    The seam `build_dataset_registry` is, for the port beside it: this one also
    returns what it wrote, which a `Tracker` never does (R15.5 row 2), and
    which R0.17 lets tracking read back because spec 014 fences it. A
    test replaces it with a `FakePromptRegistry`.
    """
    return connect_prompts(
        settings.uri, auth=settings.auth, ca_bundle=settings.ca_bundle, verify=verify
    )


def say_passed_over(unreadable: Sequence[tuple[str, str]]) -> None:
    """Name on stderr each run whose manifest a command could not read (R4.30)."""
    for run_id, reason in unreadable:
        typer.echo(passed_over_line(run_id, reason), err=True)


def latest_run(
    workspace: Path, pipeline: str, *, finished: bool = False
) -> tuple[ResolvedPlan | None, str | None]:
    """The pipeline's latest run, naming each manifest passed over on the way (R4.30).

    `finished` passes over, and names, a newer run that stopped before it
    ended: a plan's `cached` is a promise only a run that finished can back
    (R4.31).
    """
    unreadable: list[tuple[str, str]] = []
    stopped: list[str] | None = [] if finished else None
    found = latest_manifest(
        workspace / RUNS_ROOT, pipeline, unreadable=unreadable, stopped=stopped
    )
    say_passed_over(unreadable)
    for run_id in stopped or ():
        typer.echo(stopped_line(run_id), err=True)
    return found


def declared_entry_points() -> dict[str, dict[str, str]] | None:
    """The entry points `dossier`'s own `pyproject.toml` declares, or `None` without one.

    An editable install runs from its source, which sits two levels above the
    package. A wheel has no source beside it, and nothing to compare (R0.18
    row 4). `[project.scripts]` is installed as `console_scripts`.
    """
    import tomllib

    import dossier

    source = Path(dossier.__file__).resolve().parents[2] / "pyproject.toml"
    if not source.is_file():
        return None
    project = tomllib.loads(source.read_text(encoding="utf-8")).get("project", {})
    if project.get("name") != "dossier":
        return None
    declared = {
        group: dict(points) for group, points in project.get("entry-points", {}).items()
    }
    if project.get("scripts"):
        declared["console_scripts"] = dict(project["scripts"])
    return declared


def installed_entry_points() -> dict[str, dict[str, str]]:
    """The entry points the installed `dossier`'s metadata holds, by group and name."""
    from importlib.metadata import distribution

    found: dict[str, dict[str, str]] = {}
    for point in distribution("dossier").entry_points:
        found.setdefault(point.group, {})[point.name] = point.value
    return found


def stale_install() -> str | None:
    """The line refusing an install made from other source than this, or `None` (R0.18)."""
    declared = declared_entry_points()
    if declared is None:
        return None
    differences = stale_entry_points(declared=declared, installed=installed_entry_points())
    return stale_install_line(differences) if differences else None


def hold_workspace(ctx: typer.Context, workspace: Path, command: str) -> None:
    """Hold the workspace until this command ends, or refuse at once, naming who has it (R20.1).

    The lock goes on the command's own context, which closes however the
    command ends -- returned, exited, raised -- so no command's body is wrapped,
    and none can forget to let go. Called before anything is read.
    """
    lock = WorkspaceLock(workspace, command=command, pid=os.getpid(), since=datetime.now(UTC))
    try:
        ctx.with_resource(lock)
    except WorkspaceHeld as held:
        typer.echo(str(held), err=True)
        raise typer.Exit(code=2) from held
