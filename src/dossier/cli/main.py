"""The `dossier` command line (specs 002, 003).

The only layer that exits the interpreter, and the only place that knows which
concrete connector, store and ledger are in play -- everything below takes them
as arguments.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from secrets import token_hex

import typer

from dossier.application.convert import (
    ConvertReport,
    HeldDocument,
    convert_source,
)
from dossier.application.datasets import EmptyGoldSet, publish_gold
from dossier.application.eval import (
    FieldSample,
    Judging,
    calibrate_fields,
    deltas_artifact,
    finish_eval,
    judge_prompt_hash,
    judge_scores,
    load_calibration,
    load_gold,
    record_comparison,
    score_run,
    scores_artifact,
    start_eval,
)
from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.plan import (
    Plan,
    build_plan,
    latest_manifest,
    pinned_documents,
)
from dossier.application.prompts import publish_prompts
from dossier.application.run import (
    MissingFromReplay,
    execute,
    key_hashes,
    replay,
    replayed_inputs,
    replayed_parts,
)
from dossier.application.sync import CHANGES_NAME, SourceReport, changes_artifact, sync_source
from dossier.config.credentials import credential_for
from dossier.config.endpoints import EndpointUnset, endpoint_for
from dossier.config.environment import environment
from dossier.config.load import (
    JUDGE_FILE,
    ConfigError,
    load_calibration_sample,
    load_fields,
    load_judge_rubrics,
    load_judge_thresholds,
    load_output_schemas,
    load_pipeline,
    load_sources,
)
from dossier.domain.conversion import (
    PART_SUFFIX,
    PART_TYPE,
    NoConverter,
    part_name,
    unpack_parts,
)
from dossier.domain.conversion import used as used_converters
from dossier.domain.datasets import PublishedDataset
from dossier.domain.gold import gold_set_hash
from dossier.domain.grounding import GROUNDED, judge_name, judged_states
from dossier.domain.hashing import short, text_hash
from dossier.domain.judges import Calibration, NotCalibrated, withholding
from dossier.domain.model_id import provider_of
from dossier.domain.ports import (
    DatasetRegistry,
    ImagePart,
    ModelClient,
    PromptRegistry,
    Tracker,
    VersionRegistry,
)
from dossier.domain.resolution import PinnedConverter, check_kinds, moved_since, run_id
from dossier.domain.scoring import (
    check_same_documents,
    compare_totals,
    overall,
    per_field,
    weakest,
)
from dossier.domain.store import replay_path
from dossier.domain.sync import DocumentCollision, State, one_document_per_key
from dossier.domain.tracking import (
    NAMESPACE,
    TrackingSettings,
    comparison_description,
    convert_description,
    count_metrics,
    eval_description,
    experiment_name,
    judge_line,
    label_for,
    name_template,
    namespace,
    namespaced,
    run_name,
    step_line,
    sync_description,
)
from dossier.domain.tracking import capture as capture_setting
from dossier.domain.tracking import settings as tracking_settings
from dossier.domain.tracking import tags as tracking_tags
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.connectors.registry import (
    UnknownSourceType,
    build_connector,
    declared_keys,
)
from dossier.infrastructure.converters.registry import installed_converters
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.models.openai_compatible import ModelRequestFailed
from dossier.infrastructure.models.registry import UnknownProvider, available_providers
from dossier.infrastructure.models.registry import provider as model_provider
from dossier.infrastructure.store import SnapshotStore
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

app = typer.Typer(add_completion=False)


@app.callback()
def main() -> None:
    """Collect documents, audit them, and prove the result.

    A callback is declared so that `sync` stays a sub-command. Typer collapses
    a single-command app into a bare invocation, and `dossier <pipeline>` is
    not the interface the specs describe -- `run` and `eval` join it later.
    """


@app.command()
def sync(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    full: bool = typer.Option(
        False,
        "--full",
        help="Ask every source for a full listing, so what it dropped is tombstoned.",
    ),
    label: str = typer.Option(
        "", "--label", help="A name for this record, in MLflow (R10.11).", metavar="NAME"
    ),
) -> None:
    """Fetch only what changed for the sources a pipeline declares (R2.12).

    `--full` lists every source without a window (R2.22). A source that narrows
    its listings is subtracted from only against a full one, which otherwise
    happens on the first sync and on a `fields` change alone.
    """
    workspace = Path.cwd()
    started_at = datetime.now(UTC)

    try:
        config = load_pipeline(
            _pipeline_path(workspace, pipeline), providers=available_providers()
        )
        declared = {
            source.id: source
            for source in load_sources(workspace / "sources.yaml", connectors=declared_keys())
        }
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    missing = [name for name in config.synced_sources if name not in declared]
    if missing:
        typer.echo(
            f"pipeline {pipeline!r} names sources not in sources.yaml: {missing}", err=True
        )
        raise typer.Exit(code=2)

    tracker, experiment = _tracking_for(workspace, pipeline, kind="sync")

    store = SnapshotStore(workspace)
    reports: list[SourceReport] = []
    # What this sync printed about its work, kept so the record can hold
    # the same lines rather than a second rendering of the same counts
    # (R11.17). The per-item lines are not here: `changes.json` already
    # carries them in full, and a description is a summary (R11.6).
    printed: list[str] = []

    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            source = declared[name]
            try:
                # Read here, by the one package that reads the environment, and
                # handed to the connector. Infrastructure may not go looking for
                # it itself, and the layer contract enforces that (R1.8). Read
                # through the same environment an endpoint is -- the shell, with
                # `.env` beneath it -- so one file holds every per-machine value
                # (R1.8 row 5, R9.11).
                connector = build_connector(
                    source,
                    workspace=workspace,
                    credential=credential_for(source, environ=environment(workspace)),
                )
            except (UnknownSourceType, ValueError, ConfigError) as error:
                typer.echo(str(error), err=True)
                raise typer.Exit(code=2) from error

            report = sync_source(
                config=source,
                connector=connector,
                store=store,
                ledger=ledger,
                now=started_at,
                full=full,
            )
            reports.append(report)
            printed.append(_source_line(report))
            typer.echo(printed[-1])
            for line in _named_lines(report):
                typer.echo(line)
            for key, error in report.failures:
                # With the error the source gave: "failed" alone sends someone to
                # guess whether it was a timeout, a permission or a bad item
                # (R2.13 row 4).
                typer.echo(f"  {report.source_id}: {key} failed: {error}", err=True)

    written = sum(report.snapshots_written for report in reports)
    tombstoned = sum(report.tombstoned for report in reports)
    printed.append(f"ledger updated · {written} new snapshots · {tombstoned} tombstoned")
    typer.echo(printed[-1])

    if tracker is not None:
        # One MLflow run of the per-source counts the lines above printed, under
        # the same names, and no traces (R11.4).
        tracker.start_run(
            experiment=experiment or "",
            name=run_name(
                kind="sync",
                values={
                    "pipeline": pipeline,
                    "started": f"{started_at:%Y%m%dT%H%M%SZ}",
                    "label": label_for(label, environment(workspace)),
                },
                environ=environment(workspace),
            ),
            tags=tracking_tags(
                kind="sync",
                pipeline=pipeline,
                label=label_for(label, environment(workspace)),
                environ=environment(workspace),
            ),
        )
        # Which dossier fetched this, on the record of the fetching
        # (R11.19). The ledger holds no such field, so a sync whose counts
        # look wrong could not be tied to a version at all.
        tracker.log_params({"dossier_version": version("dossier")})
        metrics: dict[str, float] = {}
        for report in reports:
            metrics.update(
                count_metrics(
                    kind="sync",
                    source=report.source_id,
                    counts={
                        "known": report.known,
                        "changed": report.changed,
                        "new": report.new,
                        "fetched": report.fetched,
                        "failed": len(report.failed),
                    },
                )
            )
        tracker.log_metrics(metrics)
        # What the lines under each source named, handed over as the report's
        # own list rather than read back from the ledger (R11.6).
        tracker.log_artifact(CHANGES_NAME, changes_artifact(reports))
        # Written as the run closes, because none of these counts exist
        # until the sources have been asked (R11.17).
        tracker.describe(sync_description(pipeline=pipeline, lines=printed))
        failed_items = any(report.failed for report in reports)
        tracker.end_run(status="FAILED" if failed_items else "FINISHED")

    failed = [key for report in reports for key in report.failed]
    if failed:
        typer.echo(f"{len(failed)} item(s) failed: {', '.join(sorted(failed))}", err=True)
        raise typer.Exit(code=1)


def _source_line(report: SourceReport) -> str:
    """One line per source, in the shape the design deck publishes (R2.13).

    A source where nothing changed is still printed. A silent source is
    indistinguishable from one that was skipped, and the whole promise of
    incremental sync is that you can see what it did.
    """
    return (
        f"{report.source_id}  {report.known} known · {report.changed} changed · "
        f"{report.new} new -> {report.fetched} fetched"
    )


def _named_lines(report: SourceReport) -> list[str]:
    """What moved and what left, one item per line under its source (R2.18, R2.20).

    `1 changed` over four thousand items is not something a person can check,
    and `1 tombstoned` says something left and not what. Both addresses of a
    changed item are printed in full: an 8-character prefix reads well and
    opens nothing, and the point of the line is to be able to diff the two
    files it names.
    """
    return [
        *(f"      {item.key}  {item.held} -> {item.now}" for item in report.repointed),
        *(f"      {key}  tombstoned" for key in report.departed),
    ]


def _pipeline_path(workspace: Path, name: str) -> Path:
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


def build_tracker(settings: TrackingSettings) -> Tracker:
    """The tracker a command records to, checked before any work (R10.5).

    `connect` refuses, naming what to fix, when the `tracking` extra is missing
    or no server answers. A named function for the reason `build_model_client`
    is one: it is the seam the composition root hands to a use case, and a test
    replaces it with a `FakeTracker`.
    """
    return connect(settings.uri)


def _tracking_for(
    workspace: Path, pipeline: str, *, kind: str, gold: str | None = None
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
        # With the rest of this machine's tracking settings, before any work: a
        # prefix composed into a name only once a command was at work reached
        # `eval` and `calibrate` as a traceback, with their run open (R14.10).
        namespace(environ)
        return BestEffortTracker(build_tracker(tracking)), experiment
    except (ValueError, TrackingUnavailable) as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error


def _version_experiment(workspace: Path, pipeline: str) -> str:
    """Where this pipeline's versions live: its **run** experiment (spec 013).

    Not the experiment of the command doing the registering. A version is
    produced by a run and merely measured by an eval, so it belongs beside the
    runs that produced it -- and an eval registering into its own experiment
    would give one pipeline two Models tabs that never meet. Spec 012 puts a
    dataset in the eval experiment on the same reasoning, from the other end.
    """
    return experiment_name(
        kind="run", pipeline=pipeline, gold="", environ=environment(workspace)
    )


def _versions_for(workspace: Path) -> VersionRegistry | None:
    """The version registry for this workspace, or `None` when it cannot be built.

    `None` rather than raising. `_tracking_for` has already refused a server
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


def _capture_for(workspace: Path, pipeline: str) -> str:
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


class _BuiltOnFirstCall:
    """A model client that is not built until a stage first asks it something.

    A run served entirely from cache reaches no model, so it needs no endpoint
    and no client (R9.2 row 5, R0.9). Building one up front made a fully cached
    run fail on a machine that could have completed it. `model_id` is known
    without building anything: it is part of every key, and the keys are what
    decide whether a call happens at all.

    `build_model_client` is looked up when the first call is made rather than
    bound here, so the seam a test replaces is the one this reaches.
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._client: ModelClient | None = None

    def complete(
        self,
        prompt: str,
        *,
        schema: dict | None = None,
        parts: Sequence[ImagePart] = (),
    ) -> str:
        if self._client is None:
            self._client = build_model_client(self.model_id)
        return self._client.complete(prompt, schema=schema, parts=parts)


@app.command()
def run(
    pipeline: str = typer.Argument(
        "", help="Pipeline name under pipelines/. Not needed with --replay."
    ),
    plan: bool = typer.Option(False, "--plan", help="Report what would run. Do nothing."),
    replay_from: str = typer.Option(
        "", "--replay", help="Reproduce a past run from runs/<run_id>/", metavar="DIR"
    ),
    label: str = typer.Option(
        "", "--label", help="A name for this record, in MLflow (R10.11).", metavar="NAME"
    ),
) -> None:
    """Execute a pipeline, report what executing it would do, or replay one (spec 004).

    `pipeline` is optional with `--replay`, because a replay reads the pipeline
    name from the manifest and consults no configuration at all (R4.7). Requiring
    it made spec 004's own documented invocation --
    `dossier run --replay runs/<run_id>/` -- fail on a missing argument that was
    then ignored.
    """
    if replay_from:
        _replay(Path.cwd(), Path(replay_from))
        return

    if not pipeline:
        typer.echo("a pipeline name is required unless --replay is given", err=True)
        raise typer.Exit(code=2)

    if not plan:
        _execute(Path.cwd(), pipeline, label=label)
        return

    workspace = Path.cwd()

    try:
        path = _pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
        declared = {
            source.id: source
            for source in load_sources(workspace / "sources.yaml", connectors=declared_keys())
        }
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    documents: dict[str, str] = {}
    # The same requests a run would make of the converters, so the plan pins the
    # same set the run will (R8.9) -- otherwise a plugin the corpus never needed
    # would print `converters changed` against a manifest that never named it.
    requests: list[tuple[str, Sequence[str] | None]] = []
    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            if name in declared:
                rows = ledger.rows(name)
                documents.update(pinned_documents(rows))
                requests.extend(
                    (row.media_type, declared[name].convert)
                    for row in rows
                    if row.state is not State.TOMBSTONED
                )

    previous, previous_id = latest_manifest(workspace / "runs", pipeline)

    # Keyed exactly as the run will be, from the same files, through the same
    # derivation (R4.12): `cached` here is a promise the run keeps.
    prompt_hashes, schema_hashes = key_hashes(
        config,
        prompts={
            step.id: (path.parent / step.prompt).read_text(encoding="utf-8")
            for step in config.steps
        },
        schemas=load_output_schemas(config, path),
    )

    try:
        report = build_plan(
            pipeline=config,
            pipeline_hash=text_hash(path),
            documents=documents,
            previous=previous,
            previous_id=previous_id,
            prompt_hashes=prompt_hashes,
            schema_hashes=schema_hashes,
            # Read here, as the run reads them, because a raised converter
            # version changes the text every step reads and therefore every key
            # above it (R5.4). Listing entry points opens no file a plan may not
            # open and builds no client, so R4.6 is untouched.
            converters=[
                PinnedConverter(
                    id=c.id, version=c.version, media_type=c.media_type, kind=c.kind
                )
                for c in used_converters(requests=requests, available=installed_converters())
            ],
        )
    except ValueError as error:
        # Resolution failed, so nothing ran and nothing was written (R4.1).
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    for line in _plan_lines(report):
        typer.echo(line)


def _plan_lines(report: Plan) -> list[str]:
    """The plan as a person reads it: one step per line, evidence indented.

    A step whose inputs moved prints what they were and what they are now. That
    is the whole point of the command -- an insertion looks local in the YAML and
    silently re-points every relative reference below it (R4.5). A step whose
    documents moved prints which ones, for the same reason: "documents changed"
    over a corpus of four thousand is not something a person can check.
    """
    lines = [
        f"{report.resolved.pipeline}  {len(report.resolved.documents)} document(s) · "
        f"model {report.resolved.model}"
    ]
    if report.compared_against is None:
        lines.append("no previous run to compare against")
    else:
        lines.append(f"compared against {report.compared_against}")

    for step in report.steps:
        marker = "!" if step.rerunning else " "
        lines.append(f"{marker} {step.step.id}: {step.status.value}")
        if step.was is not None:
            lines.append(f"      was: [{', '.join(step.was)}]")
            lines.append(f"      now: [{', '.join(step.step.inputs)}]")
        if step.moved:
            lines.append(f"      moved: [{', '.join(step.moved)}]")

    lines.append(
        f"{report.rerunning} of {len(report.steps)} step(s) would run · nothing written"
    )
    return lines


@app.command()
def convert(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    label: str = typer.Option(
        "", "--label", help="A name for this record, in MLflow (R10.11).", metavar="NAME"
    ),
) -> None:
    """Convert what a pipeline needs, and report what that cost (R8.8).

    Optional: `run` converts what it needs anyway, and conversion is idempotent
    and cached, so running this early costs nothing. It exists so the text a
    stage will actually see can be inspected before a single model call is made
    -- which on a PDF-heavy corpus is usually where the surprises are.
    """
    workspace = Path.cwd()
    started_at = datetime.now(UTC)

    try:
        config = load_pipeline(
            _pipeline_path(workspace, pipeline), providers=available_providers()
        )
        declared = {
            source.id: source
            for source in load_sources(workspace / "sources.yaml", connectors=declared_keys())
        }
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    # Before any conversion, as sync checks before any fetch: a server nobody can
    # reach is refused now rather than after the work nobody can then inspect
    # (R10.5).
    tracker, experiment = _tracking_for(workspace, pipeline, kind="convert")

    converters = installed_converters()
    store = SnapshotStore(workspace)
    cache = ArtifactCache(workspace, namespace="convert")
    reports: list[ConvertReport] = []

    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            source = declared.get(name)
            if source is None:
                continue
            held = {
                row.key: HeldDocument(snapshot=row.snapshot, media_type=row.media_type)
                for row in ledger.rows(name)
                if row.state is not State.TOMBSTONED
            }
            try:
                reports.append(
                    convert_source(
                        source_id=name,
                        documents=held,
                        kinds=source.convert,
                        converters=converters,
                        store=store,
                        cache=cache,
                    )
                )
            except NoConverter as error:
                # A configuration error, not a per-document one: the pipeline is
                # not set up to read what it was pointed at, so nothing converts
                # and the fix is an installation (R8.5).
                typer.echo(str(error), err=True)
                raise typer.Exit(code=2) from error

    # Kept as they are printed, so the record holds the command's own lines
    # rather than a second rendering of the same counts (R11.17).
    printed: list[str] = []
    for report in reports:
        printed.append(_convert_line(report))
        typer.echo(printed[-1])
        for failure in report.failed:
            typer.echo(f"    {failure.document}: {failure.error}")

    converted = sum(report.converted for report in reports)
    cached = sum(report.cached for report in reports)
    printed.append(f"cache updated · {converted} converted · {cached} cached")
    typer.echo(printed[-1])

    failed = [failure for report in reports for failure in report.failed]

    if tracker is not None:
        # One MLflow run of the per-source counts the lines above printed, under
        # the same names, and no traces (R11.4). Recorded before the non-zero
        # exit below, not after it: a convert that failed is still a convert that
        # happened, and a record written only on success would make a failure
        # look like a command nobody ran.
        tracker.start_run(
            experiment=experiment or "",
            name=run_name(
                kind="convert",
                values={
                    "pipeline": pipeline,
                    "started": f"{started_at:%Y%m%dT%H%M%SZ}",
                    "label": label_for(label, environment(workspace)),
                },
                environ=environment(workspace),
            ),
            tags=tracking_tags(
                kind="convert",
                pipeline=pipeline,
                label=label_for(label, environment(workspace)),
                environ=environment(workspace),
            ),
        )
        tracker.log_params({"dossier_version": version("dossier")})
        metrics: dict[str, float] = {}
        for report in reports:
            metrics.update(
                count_metrics(
                    kind="convert",
                    source=report.source_id,
                    counts={
                        "held": report.held,
                        "converted": report.converted,
                        "cached": report.cached,
                        "failed": len(report.failed),
                    },
                )
            )
        tracker.log_metrics(metrics)
        tracker.describe(convert_description(pipeline=pipeline, lines=printed))
        tracker.end_run(status="FAILED" if failed else "FINISHED")

    if failed:
        # A failure is not zero work. Exiting zero here would make a run that
        # converted nothing indistinguishable from one that had nothing to do
        # (R8.6, R1.9's shape).
        raise typer.Exit(code=1)


def _convert_line(report: ConvertReport) -> str:
    """One line per source, in the shape sync already uses (R2.13, R8.8)."""
    line = (
        f"{report.source_id}  {report.held} held · {report.converted} converted · "
        f"{report.cached} cached"
    )
    return line if not report.failed else f"{line} · {len(report.failed)} failed"


def _replay(workspace: Path, directory: Path) -> None:
    """`dossier run <pipeline> --replay runs/<run_id>/` (R4.7).

    The manifest is the only input. `pipeline.yaml` is not read -- not to check
    it agrees, not to warn that it has changed -- because a replay that consulted
    it would be reproducing today's configuration rather than the run.
    """
    path = directory / MANIFEST_NAME
    if not path.is_file():
        typer.echo(f"no manifest at {path}", err=True)
        raise typer.Exit(code=2)

    manifest = Manifest.read(path)
    cache = ArtifactCache(workspace, namespace="convert")
    # A replay id has the form of a run id and is minted the same way. Where
    # what is reproduced goes: under the run, never over it (R0.12).
    destination = replay_path(manifest.run_id, run_id(datetime.now(UTC), token_hex(2)))

    try:
        # The conversions this run produced, read back by their keys rather than
        # recomputed. A replay therefore needs no converter installed at all --
        # the same shape as needing no model client. Raising a converter version
        # is how R5.4 invalidates conversions, so re-converting would produce
        # text the original run never saw (R4.7, R4.9).
        store = SnapshotStore(workspace)
        text = replayed_inputs(manifest, store=store, cache=cache)
        report = replay(
            manifest=manifest,
            document_text=text,
            # The containers this run fanned a per_part step out over, read back
            # by their keys like the text beside them (R4.14).
            document_parts=replayed_parts(manifest, store=store, cache=cache),
            cache=ArtifactCache(workspace, namespace="stage"),
            destination=workspace / destination,
        )
    except MissingFromReplay as error:
        # A replay may fail; it may never substitute other content (R4.7 row 4).
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    typer.echo(f"replayed {manifest.run_id} · {manifest.plan.pipeline}")
    for step in report.steps:
        typer.echo(f"  {step.step}: {step.artifacts} artifact(s) from cache")
    reproduced = f"{report.cache_hits} artifact(s) reproduced"
    typer.echo(f"{reproduced} · no model calls · written to {destination}/")


def _execute(workspace: Path, pipeline: str, *, label: str = "") -> None:
    """`dossier run <pipeline>` (spec 004, spec 005)."""
    try:
        path = _pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
        declared = {
            source.id: source
            for source in load_sources(workspace / "sources.yaml", connectors=declared_keys())
        }
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    # Before a byte is fetched, because this is knowable from the two config
    # files alone (R4.13). `execute` checks it again for a caller that never
    # came through here, but by then conversion has already run -- and R8.5
    # would report the same pipeline as an installation problem, which is the
    # other failure with the other fix.
    try:
        check_kinds(
            steps=config.steps,
            sources=[declared[name] for name in config.sources if name in declared],
            reference=[declared[name] for name in config.reference if name in declared],
        )
    except ValueError as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    tracker, experiment = _tracking_for(workspace, pipeline, kind="run")
    capture = _capture_for(workspace, pipeline) if tracker is not None else "full"
    # On the same switch as the tracker: a version is part of the record,
    # and R10.1 is one decision about whether there is a record at all.
    versions = _versions_for(workspace) if tracker is not None else None
    # Same switch, same reason (R14.7 row 3): with tracking off the registry
    # is not merely unlinked but unasked, because a run reaching a server it
    # was told not to use is the thing R10.1 decides.
    prompt_registry = _prompt_registry_for(workspace) if tracker is not None else None

    store = SnapshotStore(workspace)
    converters = installed_converters()
    text: dict[str, str] = {}
    # Every converted kind, not only `markdown`, so a step naming one can be
    # handed it (R3.11). A kind whose artifact is not text is absent from here
    # and reaches a step another way; this is what a prompt placeholder holds.
    content: dict[str, dict[str, str]] = {}
    parts: dict[str, dict[str, list[tuple[str, ImagePart]]]] = {}
    documents: dict[str, str] = {}
    media_types: dict[str, str] = {}
    by_source: dict[str, list[str]] = {}
    # What each held document asked of the converters, so the manifest can pin
    # the ones the run used rather than the ones this machine carries (R8.9).
    requests: list[tuple[str, Sequence[str] | None]] = []
    started_at = datetime.now(UTC)
    this_run = run_id(started_at, token_hex(2))
    convert_cache = ArtifactCache(workspace, namespace="convert")
    unreadable: list[tuple[str, str, str]] = []

    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            source = declared.get(name)
            if source is None:
                continue
            held = {
                row.key: HeldDocument(snapshot=row.snapshot, media_type=row.media_type)
                for row in ledger.rows(name)
                if row.state is not State.TOMBSTONED
            }
            try:
                converted = convert_source(
                    source_id=name,
                    documents=held,
                    kinds=source.convert,
                    converters=converters,
                    store=store,
                    cache=convert_cache,
                    run_id=this_run,
                    dossier_version=version("dossier"),
                )
            except NoConverter as error:
                typer.echo(str(error), err=True)
                raise typer.Exit(code=2) from error
            requests.extend((document.media_type, source.convert) for document in held.values())
            by_source[name] = list(converted.present)
            text.update(converted.text)
            for kind in {a.kind for d in converted.documents for a in d.artifacts}:
                produced = converted.content(kind)
                decoded = {}
                for key, payload in produced.items():
                    try:
                        decoded[key] = payload.decode("utf-8")
                    except UnicodeDecodeError:
                        # Not text. A kind like `page_images` is bytes, and a
                        # prompt placeholder cannot hold it -- it reaches a step
                        # as parts rather than as a substitution.
                        continue
                if decoded:
                    content.setdefault(kind, {}).update(decoded)
                # A kind whose artifact is a container of parts, unpacked once
                # here so a per_part step can fan out over it (R3.12, R8.11).
                for key, payload in produced.items():
                    try:
                        unpacked = unpack_parts(payload)
                    except ValueError:
                        continue
                    parts.setdefault(kind, {})[key] = [
                        (part_name(n, PART_SUFFIX), ImagePart(media_type=PART_TYPE, data=b))
                        for n, b in enumerate(unpacked, 1)
                    ]
            # Every document that converted, not only those that converted to
            # text. A source rendered to pictures alone would otherwise convert
            # successfully and then be absent from the run entirely (R6.15).
            documents.update({key: held[key].snapshot for key in converted.present})
            media_types.update({key: held[key].media_type for key in converted.present})
            # A document that could not be read is not silently absent from the
            # run. It is excluded from what gets audited -- the rest of the work
            # survives it -- and it is named, with its reason, and the command
            # exits non-zero (R8.6).
            unreadable.extend(
                (name, failure.document, failure.error or "conversion failed")
                for failure in converted.failed
            )

    prompts = {
        step.id: (path.parent / step.prompt).read_text(encoding="utf-8")
        for step in config.steps
    }
    # What each step's declaration contributes: the JSON Schema generated from it
    # for the model (R6.10), and the declaration's own hash for the key (R6.11).
    schemas = load_output_schemas(config, path)

    try:
        one_document_per_key(by_source)
    except DocumentCollision as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    # A new run resolves against what is held now, and says so when that is
    # not what the last run read: the one moment a person needs to know two
    # runs are not over the same evidence, before R7.8 refuses to compare them
    # (R4.9 row 4). Before any step runs, so the warning is read, not scrolled.
    previous, previous_id = latest_manifest(workspace / "runs", pipeline)
    if previous is not None:
        moved = moved_since(previous.documents, documents)
        if moved:
            listed = ", ".join(f"{key} {how}" for key, how in moved.items())
            typer.echo(f"warning: the source has moved since run {previous_id}: {listed}")

    try:
        report = execute(
            workspace=workspace,
            pipeline=config,
            pipeline_hash=text_hash(path),
            documents=documents,
            media_types=media_types,
            document_text=text,
            document_content=content,
            document_parts=parts,
            schemas=schemas,
            prompts=prompts,
            # Built at the first cache miss, never before. That also keeps it
            # behind resolution: constructed up front, a pipeline with both a
            # bad reference and an unreachable model reported the model (R4.1).
            model=_BuiltOnFirstCall(config.model),
            cache=ArtifactCache(workspace, namespace="stage"),
            tracker=tracker,
            experiment=experiment,
            environ=environment(workspace),
            label=label_for(label, environment(workspace)),
            capture=capture,
            versions=versions,
            prompt_registry=prompt_registry,
            # The same variable a publish reads, so a run asks for the name it
            # would have published under (R14.8 row 3).
            prompt_prefix=environment(workspace).get(NAMESPACE, ""),
            version_experiment=experiment or "",
            run_id=this_run,
            started_at=started_at,
            dossier_version=version("dossier"),
            # What each source was told to make, so a step asking for a kind
            # nobody produces is refused before anything else happens (R4.13).
            source_configs=declared,
            converters=[
                PinnedConverter(
                    id=c.id, version=c.version, media_type=c.media_type, kind=c.kind
                )
                for c in used_converters(requests=requests, available=converters)
            ],
        )
    except ValueError as error:
        # Resolution failed, so nothing ran and nothing was written (R4.1).
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error
    except (EndpointUnset, UnknownProvider) as error:
        # The first cache miss needed a model this machine cannot reach. The run
        # stops there, before any model was asked (R9.2 row 3).
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error
    except ModelRequestFailed as error:
        # The endpoint refused or could not be reached. Named by URL and status,
        # never by key (R9.8 row 1); answers already cached stay cached.
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    for source, document, reason in unreadable:
        typer.echo(f"  {source}: {document} could not be converted: {reason}", err=True)

    typer.echo(f"run {report.run_id} · {report.manifest_path}")
    if tracker is not None:
        # The one thing tracking changes: what a person reads, never what is
        # written to disk (R10.4 row 3). The MLflow run is named after this run.
        typer.echo(f"recorded to MLflow: {experiment} · run {report.run_id}")
        if tracker.lost_traces:
            # The record has a gap; the run does not. Said, so the gap is not
            # read as documents that were never processed (R10.6).
            typer.echo(
                f"warning: {tracker.lost_traces} trace(s) could not be recorded", err=True
            )
        if getattr(versions, "lost_versions", 0):
            # Said for the reason a lost trace is (R10.6): a Models tab with
            # nothing in it should not read as a pipeline nobody ever ran
            # (R13.5 row 2). The run itself is untouched.
            typer.echo("warning: the pipeline version could not be recorded", err=True)
    for step in report.steps:
        cached = len(step.served_from_cache)
        # Only when there are any. A `· 0 described` on every line of every run
        # of every text pipeline would be noise, and the number is interesting
        # precisely because it is usually absent (R6.15).
        # Counted the same way and absent for the same reason (R6.16). A finding
        # is not a failure -- the document produced usable output and every
        # artifact was written -- so it is its own number beside `failed` rather
        # than folded into it, and the exit code below does not see it.
        findings = step.findings
        # Composed in the domain, because the record the run just closed holds
        # this same line (R11.17): two format strings would drift, and the drift
        # would read as the terminal and MLflow disagreeing (spec 011).
        typer.echo(
            "  "
            + step_line(
                step=step.step,
                documents=len(step.results),
                cached=cached,
                failed=len(step.failed),
                described=step.described,
                findings=len(findings),
            )
        )
        for document, check in findings:
            # The detail `check_field` composed, verbatim. It already names the
            # field and says which rule was not met; repeating either here would
            # be this message deciding it knows better than the check did.
            typer.echo(f"    {document}  {check.detail}")

    for step, document in report.failed:
        typer.echo(f"    {step} failed on {document}", err=True)

    # Either kind of failure means this audit covered less than the corpus. A
    # zero exit here would let anything reading `$?` quote it as clean.
    if report.failed or unreadable:
        raise typer.Exit(code=1)


def _has_per_part(config) -> bool:
    """Whether this pipeline has a step that can answer from a picture (R7.20).

    A `per_part` step declaring an output is the only thing that can produce a
    `described` verdict (R3.12, R6.15). Asked here and handed to the domain,
    which decides what follows from it -- the loader asks the same question of
    the same shape when it refuses a missing bar.
    """
    return any(step.mode == "per_part" and step.output is not None for step in config.steps)


def _held_content(workspace: Path, config) -> tuple[dict[str, str], dict[str, list[ImagePart]]]:
    """The converted text and the pages of every document the workspace holds (R7.14).

    The same path `dossier convert` walks -- ledger rows, then conversion -- and
    for a reason worth stating: a calibration is about a judge and a rubric, not
    about any past run, so there is no manifest to reproduce and nothing to
    replay. What the judge is shown is what the workspace holds today.
    """
    try:
        declared = {
            source.id: source
            for source in load_sources(workspace / "sources.yaml", connectors=declared_keys())
        }
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    converters = installed_converters()
    store = SnapshotStore(workspace)
    cache = ArtifactCache(workspace, namespace="convert")

    text: dict[str, str] = {}
    pages: dict[str, list[ImagePart]] = {}
    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            source = declared.get(name)
            if source is None:
                continue
            held = {
                row.key: HeldDocument(snapshot=row.snapshot, media_type=row.media_type)
                for row in ledger.rows(name)
                if row.state is not State.TOMBSTONED
            }
            try:
                report = convert_source(
                    source_id=name,
                    documents=held,
                    kinds=source.convert,
                    converters=converters,
                    store=store,
                    cache=cache,
                )
            except NoConverter as error:
                typer.echo(str(error), err=True)
                raise typer.Exit(code=2) from error
            text.update(report.text)
            # The pages behind every container this source produced, for the
            # judge a described field is measured against (R7.21, R7.22). Read
            # from the same conversion the text came from, so the judge is
            # shown what a run would show it.
            for kind in {a.kind for d in report.documents for a in d.artifacts}:
                for key, payload in report.content(kind).items():
                    try:
                        unpacked = unpack_parts(payload)
                    except ValueError:
                        continue
                    pages[key] = [
                        ImagePart(media_type=PART_TYPE, data=part) for part in unpacked
                    ]
    return text, pages


@app.command()
def calibrate(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    gold: str = typer.Option(..., "--gold", help="Gold set directory", metavar="DIR"),
    label: str = typer.Option(
        "", "--label", help="A name for this record, in MLflow (R10.11).", metavar="NAME"
    ),
) -> None:
    """Measure each judged field's judge against the gold set's sample (R7.14).

    Writes what it measured to `<gold>/calibrations/<field>.json`. It never
    touches `<gold>/judge.yaml`: the bar is agreed by a person, and a run able to
    move the bar it is judged against would be a judge grading its own paper
    (R7.13).
    """
    workspace = Path.cwd()

    try:
        path = _pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    declaring = [step for step in config.steps if step.output is not None]
    if len(declaring) != 1:
        # Spec 007 scores "the output" and does not yet say which step's output
        # that is when several declare one. Refused rather than guessed, as
        # `eval` refuses it.
        typer.echo(
            f"{pipeline}: {len(declaring)} steps declare an output; "
            "calibrate reads exactly one",
            err=True,
        )
        raise typer.Exit(code=2)
    declaration = path.parent / declaring[0].output

    try:
        rubrics = load_judge_rubrics(declaration)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    if not rubrics:
        typer.echo(
            f"{pipeline}: no field is judged by a rubric, so none can be calibrated", err=True
        )
        raise typer.Exit(code=2)

    # Before any measuring work, so a server nobody can reach is refused now
    # rather than after twenty judge calls nobody can then inspect (R10.5).
    tracker, experiment = _tracking_for(workspace, pipeline, kind="calibrate", gold=gold)

    directory = workspace / gold
    documents, held_parts = _held_content(workspace, config)
    model = build_model_client(config.model)

    # One judge per state the pipeline can answer a field in, each measured on
    # its own sample and recorded beside the other (R7.22).
    states = judged_states(per_part=_has_per_part(config))

    samples: dict[str, FieldSample] = {}
    for field, named in sorted(rubrics.items()):
        # Against the pipeline's own directory, as `prompts/` and `output` are:
        # the declaration lives in `schemas/` and the rubric beside it in
        # `rubrics/`, so resolving against the declaration would look for
        # `schemas/rubrics/...`.
        rubric = path.parent / named
        for state in states:
            name = judge_name(field, state)
            try:
                samples[name] = FieldSample(
                    cases=load_calibration_sample(directory, name),
                    rubric=rubric.read_text(encoding="utf-8"),
                    rubric_hash=text_hash(rubric),
                    field=field,
                    state=state,
                )
            except ConfigError as error:
                typer.echo(f"{name}: {error}", err=True)
                raise typer.Exit(code=2) from error

    try:
        measured = calibrate_fields(
            model,
            directory=directory,
            samples=samples,
            documents=documents,
            judge_model=config.model,
            parts=held_parts,
            tracker=tracker,
            experiment=experiment or "",
            environ=environment(workspace),
            started=f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
            label=label_for(label, environment(workspace)),
            pipeline=pipeline,
            dossier_version=version("dossier"),
            # Best-effort, as the eval's is (R14.9): a server with no prompt
            # store costs the link and never the measurement.
            prompt_registry=_prompt_registry_for(workspace) if tracker is not None else None,
            prompt_prefix=environment(workspace).get(NAMESPACE, ""),
            # As bytes, as `record_eval` reads them: the hash has to move when
            # any answer moves (R11.3 row 2).
            gold_files={
                gold_file.name: gold_file.read_bytes()
                for gold_file in sorted(directory.glob("*.json"))
            },
        )
    except NotCalibrated as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    for field, calibration in sorted(measured.items()):
        # In the domain for the reason the run's step line is: `calibrate_fields`
        # put this same line on the record it closed (R11.17).
        typer.echo(
            judge_line(
                field=field,
                agreement=calibration.agreement,
                cases=calibration.sample_size,
                judge_model=calibration.judge_model,
            )
        )
    if tracker is not None:
        typer.echo(f"recorded to MLflow: {experiment}")


def _judge_gate(
    directory: Path, declaration: Path, pipeline_dir: Path, model: str, *, states=(GROUNDED,)
) -> tuple[dict[str, Calibration], dict[str, str]]:
    """Which judged fields may be reported, and why the rest may not (R7.15, R7.23).

    The reads are here -- the rubrics, the thresholds, each calibration file --
    and the decision is `withholding`'s, in the domain, so it is provable with
    a `Calibration` and four strings rather than a workspace.

    `states` are the grounding states this pipeline can answer a field in. Each
    is gated on its own calibration and its own bar, and a field is withheld
    whole if any of them fails: a field's percentage mixes verdicts of both
    kinds, so "0.82, of which the described half was never measured" is the
    number R7.5 refuses, arrived at more elaborately (R7.23).
    """
    rubrics = load_judge_rubrics(declaration)
    if not rubrics:
        return {}, {}

    # Absent is its own answer: a gold set with no judge.yaml has declared no
    # bar, and a field with no bar cannot be gated. Present and malformed still
    # raises, because that is a mistake somebody has to be told about (R7.13).
    thresholds = load_judge_thresholds(directory) if (directory / JUDGE_FILE).is_file() else {}

    judges: dict[str, Calibration] = {}
    withheld: dict[str, str] = {}
    prompt = judge_prompt_hash()
    for field, named in sorted(rubrics.items()):
        for state in states:
            name = judge_name(field, state)
            measured = load_calibration(directory, name)
            if measured is not None:
                judges[name] = measured
            reason = withholding(
                measured,
                judge_model=model,
                rubric_hash=text_hash(pipeline_dir / named),
                prompt_hash=prompt,
                threshold=thresholds.get(field, {}).get(state),
                threshold_file=JUDGE_FILE,
            )
            if reason is not None and field not in withheld:
                # The first failing state wins the message. Naming the state is
                # what makes the reason actionable: "never measured" sends
                # someone to `dossier calibrate`, and knowing it is the vision
                # judge that was never measured says which sample to write.
                withheld[field] = reason if state == GROUNDED else f"{state}: {reason}"

    return judges, withheld


@app.command("eval")
def eval_(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    gold: str = typer.Option(..., "--gold", help="Gold set directory", metavar="DIR"),
    compare: tuple[str, str] = typer.Option(
        (None, None), "--compare", help="Two run ids to compare, per field", metavar="A B"
    ),
    label: str = typer.Option(
        "", "--label", help="A name for this record, in MLflow (R10.11).", metavar="NAME"
    ),
) -> None:
    """Score a pipeline's latest run against a gold set, per field (spec 007).

    The run is reproduced from its own manifest and cache entries, exactly as a
    replay is, so scoring reads what the run produced and asks no model (R7.10).
    """
    workspace = Path.cwd()

    try:
        path = _pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    declaring = [step for step in config.steps if step.output is not None]
    if len(declaring) != 1:
        # Spec 007 scores "the output" against gold and does not yet say which
        # step's output that is when several declare one. Refused rather than
        # guessed, because a guess would report one step's scores as another's.
        typer.echo(
            f"{pipeline}: {len(declaring)} steps declare an output; eval scores exactly one",
            err=True,
        )
        raise typer.Exit(code=2)
    step = declaring[0]
    kinds = load_fields(path.parent / step.output)

    if compare[0] is not None:
        _compare_runs(
            workspace,
            pipeline,
            step=step.id,
            kinds=kinds,
            gold=gold,
            runs=compare,
            config=config,
            pipeline_dir=path.parent,
            declaration=path.parent / step.output,
            label=label,
        )
        return

    # After the compare branch, which records under its own kind: a comparison's
    # figures are deltas rather than accuracies, and an experiment should hold
    # runs comparable with one another (R10.2, R11.8). Before any scoring work,
    # so a server nobody can reach is refused now rather than after a
    # reproduction nobody can then inspect (R10.5).
    tracker, experiment = _tracking_for(workspace, pipeline, kind="eval", gold=gold)
    # A version is part of the record, so it rides on the same switch (R10.1).
    versions = _versions_for(workspace) if tracker is not None else None

    _, run_dir = latest_manifest(workspace / "runs", pipeline)
    if run_dir is None:
        typer.echo(
            f"{pipeline}: no run to score. Run `dossier run {pipeline}` first.", err=True
        )
        raise typer.Exit(code=2)
    manifest = Manifest.read(workspace / "runs" / run_dir / MANIFEST_NAME)

    scored, text, pages = _reproduced(workspace, manifest, step.id)
    scores = score_run(report=scored, gold=load_gold(workspace / gold), kinds=kinds)

    judges, withheld = _judge_gate(
        workspace / gold,
        path.parent / step.output,
        path.parent,
        config.model,
        states=judged_states(per_part=_has_per_part(config)),
    )
    # The gold files are re-read as bytes instead of being serialised back from
    # what `load_gold` parsed: the hash has to move when any answer moves, and a
    # round trip through the model would hide a change that only altered how a
    # file was written (R11.3 row 2).
    gold_files = {p.name: p.read_bytes() for p in sorted((workspace / gold).glob("*.json"))}
    if tracker is not None:
        # Asked for before the run opens, because whether the dataset is stale is
        # a tag, and a tag is set when a run starts (R11.7 row 2).
        # Not `scored`: that name holds the reproduced step result a few lines up.
        scored_hash = gold_set_hash(gold_files)
        published = _published_dataset(workspace, gold=gold)
        was = published.tags.get("dossier.gold_hash") if published is not None else None
        stale = was is not None and was != scored_hash
        # Opened before the judge is asked, so its traces sit inside the run
        # (R7.18 row 5); closed below with the figures the report printed.
        scored_version = start_eval(
            tracker,
            experiment=experiment or "",
            pipeline=pipeline,
            run_id=Path(run_dir).name,
            model=config.model,
            gold=gold,
            gold_files=gold_files,
            judges=judges,
            withheld=withheld,
            dataset_stale=stale,
            environ=environment(workspace),
            started=f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
            label=label_for(label, environment(workspace)),
            plan=manifest.plan,
            dossier_version=manifest.dossier_version,
            scored_at=manifest.started_at.isoformat().replace("+00:00", "Z"),
            versions=versions,
            version_experiment=_version_experiment(workspace, pipeline),
            # Unverified and best-effort, as the run's is (R14.7): a server
            # with no prompt store costs the link and never the score.
            prompt_registry=_prompt_registry_for(workspace),
            rubric_hashes={
                field: text_hash(path.parent / named)
                for field, named in load_judge_rubrics(path.parent / step.output).items()
            },
            prompt_prefix=environment(workspace).get(NAMESPACE, ""),
        )
        if published is not None:
            tracker.log_dataset(
                name=published.name,
                dataset_id=published.dataset_id,
                digest=published.digest,
            )
        if stale:
            # Named, not fixed. Republishing here would have an eval quietly
            # mutate shared tracking state, and refusing would let a stale
            # dataset block a score computed entirely from local files (R12.4).
            typer.echo(
                f"dataset {published.name} is stale: "
                f"published {was[:8]}, scored {scored_hash[:8]}"
            )
            typer.echo("  run `dossier dataset publish` to refresh it")
    # The judge decides only what the deterministic scorers left, and only for
    # a field it may be quoted on: a withheld field is not judged at all, since
    # nothing is measured for a number nobody may print (R7.17).
    scores = judge_scores(
        scores,
        report=scored,
        judging=_judging(
            workspace,
            config=config,
            pipeline_dir=path.parent,
            declaration=path.parent / step.output,
            documents=text,
            pages=pages,
            withheld=withheld,
            run_id=run_dir,
            tracker=tracker,
        ),
    )
    totals = per_field(scores, declared=list(kinds))

    # The overall covers exactly the fields it reported. Folding a withheld field
    # back into the headline would hand over the number R7.5 just refused, in the
    # figure most people read first -- and would make the terminal disagree with
    # MLflow about one run, which spec 011 exists to prevent (R11.3 row 4).
    reported = [total for total in totals if total.field not in withheld]
    summed = overall(reported)
    if summed is not None:
        # The overall figure opens the report and never closes it: every field's
        # own line follows, so it can never be all that is printed (R7.2).
        typer.echo(
            f"{_count(len(scores), 'document')} · {_count(len(reported), 'field')} · "
            f"overall {summed.percentage:.1f}%"
        )
    lowest = weakest(reported)
    scored = {total.field: total for total in totals}
    # Walked over the *declared* fields, as `--compare` is (R7.8). A withheld
    # field whose every verdict went to the judge has nothing deterministic to
    # total, so a report written from the totals dropped it -- silently, and
    # exactly where the withholding matters most (R7.15 row 5).
    for field in kinds:
        if field in withheld:
            # Named, not omitted. A line that simply vanished would read as a
            # field nobody verified (R7.3 row 4), which is a different problem
            # and wants different work (R7.15).
            typer.echo(f"  {field:<18}     -- {withheld[field]}")
            continue
        total = scored.get(field)
        if total is None:
            # Nothing verified this field, so there is nothing to report and
            # nothing was refused. Absent is not withheld (R7.3 row 4).
            continue
        marker = "   <- weakest" if field in lowest else ""
        # A judged field says how many of its verdicts the judge decided. A
        # percentage over an unknown mix of abstention and judged verdicts is
        # the silent subset R7.17 replaced.
        judged = f"   ({total.judged} judged)" if kinds[field].needs_a_judge else ""
        typer.echo(f"  {field:<18} {total.percentage:5.1f}%{judged}{marker}")
        # What the percentage above does not say (R7.25). A field at 0.0% is a
        # prompt citing nothing locatable, or a model reading the wrong figure,
        # or a gold set that moved -- three different problems told apart by the
        # detail and not by reading the figure again (R7.4 row 2).
        #
        # In `scores` order, which is the run's document order, so two evals of
        # one run read identically (R0.4). Only the misses: a correct verdict
        # has no detail worth a line.
        for score in scores:
            for result in score.scored:
                if result.field == field and not result.correct:
                    typer.echo(f"    {score.document:<14} {result.detail or 'incorrect'}")

    if tracker is not None:
        # The figures the lines above printed, recorded once rather than computed
        # a second way (R11.3).
        finish_eval(
            tracker,
            totals=totals,
            withheld=withheld,
            # Built from the figures the lines above printed, by the command that
            # printed them. MLflow is a second place to read them (R11.12).
            description=eval_description(
                run_id=Path(run_dir).name,
                pipeline=pipeline,
                model=config.model,
                pipeline_hash=manifest.plan.pipeline_hash,
                gold=Path(gold).name,
                gold_hash=gold_set_hash(gold_files),
                documents=len(manifest.plan.documents),
                totals=reported,
                withheld=withheld,
            ),
            # The per-document lines printed just above, which nothing else
            # keeps (R11.14).
            detail=scores_artifact(scores, withheld=withheld),
            # The accuracy this eval measured, recorded against the version it
            # scored as well as against this run (R13.3).
            version_id=scored_version,
        )
        typer.echo(f"recorded to MLflow: {experiment}")


def _compare_runs(
    workspace: Path,
    pipeline: str,
    *,
    step: str,
    kinds: dict,
    gold: str,
    runs: tuple[str, str],
    config,
    pipeline_dir: Path,
    declaration: Path,
    label: str = "",
) -> None:
    """`dossier eval <pipeline> --gold <dir> --compare <a> <b>` (R7.8).

    The change gate. Each run is reproduced from its own manifest and cache, so
    the comparison asks no model, and both are scored against the same gold set.
    The documents are checked before anything is scored: a delta over different
    documents would report the documents' difference as the change's effect.
    """
    # Before the manifests are even read: with tracking on, a server nobody can
    # reach refuses the command now rather than after reproducing two runs
    # nobody can then inspect (R10.5).
    tracker, experiment = _tracking_for(workspace, pipeline, kind="compare", gold=gold)

    model = config.model
    manifests: list[Manifest] = []
    for run in runs:
        path = workspace / "runs" / run / MANIFEST_NAME
        if not path.is_file():
            typer.echo(f"{pipeline}: no run {run!r} -- expected {path}", err=True)
            raise typer.Exit(code=2)
        manifest = Manifest.read(path)
        if manifest.plan.pipeline != pipeline:
            typer.echo(
                f"{pipeline}: run {run!r} is a run of {manifest.plan.pipeline!r}", err=True
            )
            raise typer.Exit(code=2)
        manifests.append(manifest)

    try:
        check_same_documents(
            *([document.key for document in m.plan.documents] for m in manifests), runs=runs
        )
    except ValueError as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    gold_documents = load_gold(workspace / gold)
    # Gated exactly as an eval is (R7.17 row 7): the change gate is the place a
    # judge's number is most likely to be quoted, and a withheld field prints
    # its reason on both sides and no delta.
    _, withheld = _judge_gate(
        workspace / gold,
        declaration,
        pipeline_dir,
        model,
        states=judged_states(per_part=_has_per_part(config)),
    )
    totals: list[tuple] = []
    for run, manifest in zip(runs, manifests, strict=True):
        scored, text, pages = _reproduced(workspace, manifest, step)
        scores = judge_scores(
            score_run(report=scored, gold=gold_documents, kinds=kinds),
            report=scored,
            judging=_judging(
                workspace,
                config=config,
                pipeline_dir=pipeline_dir,
                declaration=declaration,
                documents=text,
                pages=pages,
                withheld=withheld,
                run_id=run,
            ),
        )
        totals.append(per_field(scores, declared=list(kinds)))
    before, after = totals
    before = tuple(total for total in before if total.field not in withheld)
    after = tuple(total for total in after if total.field not in withheld)

    earlier, later = overall(before), overall(after)
    if earlier is not None and later is not None:
        # Opens the report and never closes it: the per-field rows follow, and a
        # regression hides behind a better overall figure unless they do (R7.8).
        typer.echo(
            f"compare {runs[0]} -> {runs[1]} · "
            f"{_count(len(manifests[0].plan.documents), 'document')} · "
            f"overall {earlier.percentage:.1f}% -> {later.percentage:.1f}% "
            f"({later.percentage - earlier.percentage:+.1f})"
        )
    deltas = compare_totals(before, after)
    if tracker is not None:
        # Recorded after the refusals above, so a comparison that was refused
        # records nothing: there is no delta, so there is no figure (R11.8 row 4).
        gold_files = {
            path.name: path.read_bytes() for path in sorted((workspace / gold).glob("*.json"))
        }
        published = _published_dataset(workspace, gold=gold)
        was = published.tags.get("dossier.gold_hash") if published is not None else None
        scored_hash = gold_set_hash(gold_files)
        record_comparison(
            tracker,
            experiment=experiment or "",
            pipeline=pipeline,
            dossier_version=version("dossier"),
            versions=_versions_for(workspace),
            version_experiment=_version_experiment(workspace, pipeline),
            runs=runs,
            models=(manifests[0].plan.model, manifests[1].plan.model),
            gold=gold,
            gold_files=gold_files,
            rows=deltas,
            overalls=(earlier, later),
            dataset_stale=was is not None and was != scored_hash,
            environ=environment(workspace),
            started=f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
            label=label_for(label, environment(workspace)),
            plans=(manifests[0].plan, manifests[1].plan),
            description=comparison_description(
                runs=runs,
                pipeline=pipeline,
                models=(manifests[0].plan.model, manifests[1].plan.model),
                gold=Path(gold).name,
                gold_hash=scored_hash,
                documents=len(manifests[0].plan.documents),
                rows=deltas,
                overalls=(earlier, later),
            ),
            detail=deltas_artifact(deltas, runs=runs),
            # Best-effort and unverified, as the eval's is (R14.11).
            prompt_registry=_prompt_registry_for(workspace),
            rubric_hashes={
                field: text_hash(pipeline_dir / named)
                for field, named in load_judge_rubrics(declaration).items()
            },
            withheld=withheld,
            prompt_prefix=environment(workspace).get(NAMESPACE, ""),
        )
        if published is not None:
            # The same link an eval makes, on the other command that scores
            # against a gold set (R11.10).
            tracker.log_dataset(
                name=published.name,
                dataset_id=published.dataset_id,
                digest=published.digest,
            )

    rows = {row.field: row for row in deltas}
    for field in kinds:
        if field in withheld:
            typer.echo(f"  {field:<18}     -- {withheld[field]}")
            continue
        row = rows.get(field)
        if row is None:
            continue
        was = f"{row.before.percentage:.1f}%" if row.before else "--"
        now = f"{row.after.percentage:.1f}%" if row.after else "--"
        moved = f"{row.delta:+.1f}" if row.delta is not None else "--"
        marker = "   <- regression" if row.regressed else ""
        typer.echo(f"  {row.field:<18} {was:>6} {now:>6} {moved:>6}{marker}")

    if tracker is not None and experiment is not None:
        typer.echo(f"recorded to MLflow: {experiment}")


def _judging(
    workspace: Path,
    *,
    config,
    pipeline_dir: Path,
    declaration: Path,
    documents: Mapping[str, str],
    pages: Mapping[str, Sequence[ImagePart]] | None = None,
    withheld: Mapping[str, str],
    run_id: str,
    tracker: Tracker | None = None,
) -> Judging:
    """What the judge is asked with, for the fields R7.15 lets be reported (R7.17).

    The client is built on the first call and never before: a scoring pass
    with nothing deferred to a judge asks nothing and needs no endpoint
    (R7.10), and a cache that serves every verdict never builds one (R7.18).
    """
    rubrics = {
        field: (
            (pipeline_dir / named).read_text(encoding="utf-8"),
            text_hash(pipeline_dir / named),
        )
        for field, named in sorted(load_judge_rubrics(declaration).items())
        if field not in withheld
    }
    return Judging(
        model=_BuiltOnFirstCall(config.model),
        cache=ArtifactCache(workspace, namespace="judge"),
        documents=documents,
        # What the run read as pictures, for the fields it answered from them
        # (R7.21). Empty for every pipeline that reads text, which is what the
        # default is for.
        parts=dict(pages or {}),
        rubrics=rubrics,
        judge_model=config.model,
        # What a judge's span may carry here, read as a stage's is (R10.8).
        capture=_capture_for(workspace, config.name),
        run_id=run_id,
        dossier_version=version("dossier"),
        tracker=tracker,
    )


def _reproduced(workspace: Path, manifest: Manifest, step: str):
    """One step's results as a past run produced them, served from its cache (R4.7).

    A run that cannot be reproduced stops the command by name. Recomputing it
    would score answers the run never gave. The converted text comes back too,
    and the pages beside it: a judge is shown the document as the run was
    (R7.17, R7.21), not as the workspace holds it now.
    """
    try:
        store = SnapshotStore(workspace)
        converted = ArtifactCache(workspace, namespace="convert")
        text = replayed_inputs(manifest, store=store, cache=converted)
        by_kind = replayed_parts(manifest, store=store, cache=converted)
        report = replay(
            manifest=manifest,
            document_text=text,
            # Without these a per_part run cannot be reproduced, and `eval`
            # scores a reproduction -- so it could score no such run at all
            # (R4.14).
            document_parts=by_kind,
            cache=ArtifactCache(workspace, namespace="stage"),
        )
    except MissingFromReplay as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    # Flattened by document, because a judge is shown a document's pages and
    # does not care which kind produced them (R7.21). A document appearing under
    # two container kinds is not a shape any converter here produces.
    pages = {
        document: [part for _, part in entries]
        for entries in by_kind.values()
        for document, entries in entries.items()
    }
    return next(result for result in report.steps if result.step == step), text, pages


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _published_dataset(workspace: Path, *, gold: str) -> PublishedDataset | None:
    """The dataset published for this gold set, or `None` if there is not one.

    Best effort, and deliberately. A gold set nobody has published is not an error
    -- there is simply nothing to link -- and a dataset call that fails costs the
    eval nothing, because a lost record never changes a command's outcome (R10.6).
    What is never best effort is the score: that came from the files, and nothing
    read here can reach it (R12.4).
    """
    try:
        tracking = tracking_settings(environment(workspace))
        if tracking is None:
            return None
        # Under the name a publish would have sent (R10.13).
        namespace = environment(workspace).get(NAMESPACE, "")
        return build_dataset_registry(tracking).find(namespaced(Path(gold).name, namespace))
    except Exception:
        # `TrackingUnavailable` included: an eval needs no dataset, so a server
        # that cannot hold one is no reason to refuse the command (R12.5 row 5).
        typer.echo("dataset not linked: MLflow could not be asked for it")
        return None


dataset_app = typer.Typer(
    add_completion=False,
    help="Publish a gold set to MLflow as an evaluation dataset (spec 012).",
)
app.add_typer(dataset_app, name="dataset")


def build_version_registry(settings: TrackingSettings) -> VersionRegistry:
    """The registry a pipeline version is registered through (spec 013).

    The seam a test replaces with a `FakeVersionRegistry`, as `build_tracker`
    and `build_dataset_registry` are. Wrapped best-effort here rather than at
    the call site, because `dossier run` has work to do whether or not MLflow
    can hold a logged model (R13.5).
    """
    return BestEffortVersionRegistry(connect_versions(settings.uri))


def build_dataset_registry(settings: TrackingSettings) -> DatasetRegistry:
    """The registry a gold set is published through, checked before anything is sent.

    A named function for the reason `build_tracker` is one: it is the seam the
    composition root hands to a use case, and a test replaces it with a
    `FakeDatasetRegistry`. Separate from `build_tracker` because the two are
    different ports -- this one returns what it published, which a `Tracker` may
    never do (R0.10, spec 012).
    """
    return connect_datasets(settings.uri)


@dataset_app.command("publish")
def dataset_publish(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    gold: str = typer.Option(..., "--gold", help="Gold set directory", metavar="DIR"),
) -> None:
    """Publish a gold set as the MLflow evaluation dataset named after it (R12.1).

    Reads `gold/` and sends; asks no model, reproduces no run, and writes nothing
    to disk. The dataset lands in the experiment an eval over this gold set
    records to (R10.2), so it sits beside the runs measured against it.
    """
    workspace = Path.cwd()
    environ = environment(workspace)

    try:
        _pipeline_path(workspace, pipeline)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    # The switch, the template and the server, in the order a person would fix
    # them and all before anything is sent (R12.5). Unlike every other command,
    # this one has nothing to do with tracking off: its whole output is the
    # record, so off is a refusal rather than a quiet no-op (R12.5 row 1).
    try:
        tracking = tracking_settings(environ)
        if tracking is None:
            raise ValueError(
                "publishing a dataset needs tracking on: set DOSSIER_MLFLOW_ENABLED=true "
                "and DOSSIER_MLFLOW_TRACKING_URI. A dataset is published to MLflow and "
                "nowhere else"
            )
        experiment = experiment_name(kind="eval", pipeline=pipeline, gold=gold, environ=environ)
        # Before anything is sent, and although a dataset name alone would take a
        # `/`: one namespace goes in front of every published name (R10.14 row 5).
        namespace(environ)
        registry = build_dataset_registry(tracking)
    except (ValueError, TrackingUnavailable) as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    directory = workspace / gold
    if not directory.is_dir():
        # A path that is not there and a directory holding no answers want
        # different fixes -- a corrected path, or a reviewer -- so they do not
        # share a message. A mistyped `--gold` is the likelier of the two, and
        # publishing an empty dataset under the mistyped name would be worse than
        # refusing and harder to notice.
        typer.echo(f"{pipeline}: no gold set at {gold}", err=True)
        raise typer.Exit(code=2)

    try:
        published = publish_gold(
            registry,
            gold=directory,
            experiment=experiment,
            snapshots=_held_snapshots(workspace),
            namespace=environ.get(NAMESPACE, ""),
        )
    except EmptyGoldSet as error:
        # Named as the person typed it. `EmptyGoldSet` carries the resolved path,
        # and an absolute one with this machine's separators in it is noise around
        # the one word they need to see (R12.1 row 3).
        typer.echo(f"{pipeline}: {gold}: no verified answers to publish", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(
        f"{published.name} · {_count(published.records, 'record')} · digest {published.digest}"
    )
    # The id MLflow assigned, because it is what addresses the dataset in the
    # UI and in the API. Printed and never written: a file holding it would
    # make a manifest or a cache entry depend on what a server said
    # (R12.4 row 3).
    typer.echo(f"published to MLflow: {experiment} ({published.dataset_id})")


def _held_snapshots(workspace: Path) -> dict[str, str]:
    """Every held document's snapshot address, by document key (R12.2 row 1).

    Provenance for the answers rather than a precondition for them: a gold set
    published before the first sync finds nothing here, and publishes anyway
    (R12.2 row 3).
    """
    with Ledger(workspace) as ledger:
        return {
            row.key: row.snapshot
            for source in ledger.sources()
            for row in ledger.rows(source)
            if row.state is not State.TOMBSTONED
        }


prompts_app = typer.Typer(
    add_completion=False,
    help="Publish a pipeline's prompts to MLflow's prompt registry (spec 014).",
)
app.add_typer(prompts_app, name="prompts")


def _prompt_registry_for(workspace: Path) -> PromptRegistry | None:
    """The registry a run asks which version carries the prompt it rendered.

    Best-effort in the sense `_versions_for` is: a server that cannot be reached
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
    returns what it wrote, which a `Tracker` may never do (R0.10, spec 014). A
    test replaces it with a `FakePromptRegistry`.
    """
    return connect_prompts(settings.uri, verify=verify)


@prompts_app.command("publish")
def prompts_publish(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
) -> None:
    """Publish every prompt and rubric the pipeline names, as MLflow prompt versions.

    Writes to MLflow and nowhere else: no prompt is ever read back into a run,
    a key or a file, and the files under `pipelines/<name>/` stay the only
    source a run renders from (R14.5). A prompt already at the hash it would be
    published under is not sent again (R14.4).
    """
    workspace = Path.cwd()
    environ = environment(workspace)

    try:
        path = _pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
    except ConfigError as error:
        # R14.1 row 4: a publish reads the pipeline a run reads, and gets no
        # further than the run would. A prompt file that is not there is
        # already refused here, by R3.6.
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    try:
        tracking = tracking_settings(environ)
        if tracking is None:
            raise ValueError(
                "publishing prompts needs tracking on: set DOSSIER_MLFLOW_ENABLED=true "
                "and DOSSIER_MLFLOW_TRACKING_URI. A prompt version is published to "
                "MLflow and nowhere else"
            )
        # Before the registry is built, which probes the server: a namespace that
        # is retired or that MLflow would reject is refused before any work
        # (R10.14, R10.15).
        chosen = namespace(environ)
        registry = build_prompt_registry(tracking)
    except (ValueError, TrackingUnavailable) as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    directory = path.parent
    try:
        rubrics = {
            step.id: load_judge_rubrics(directory / step.output)
            for step in config.steps
            if step.output
        }
        published = publish_prompts(
            registry,
            config=config,
            directory=directory,
            rubrics=rubrics,
            prefix=chosen,
        )
    except (ConfigError, ValueError) as error:
        # The illegal pipeline name lands here (R14.1 row 5): composed, refused,
        # and nothing sent -- rather than an MLflow traceback partway through.
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(f"{config.name} · {_count(len(published), 'prompt')}")
    width = max((len(prompt.name) for prompt in published), default=0)
    for prompt in published:
        state = "created" if prompt.created else "unchanged"
        typer.echo(
            f"  {prompt.name:<{width}}  {short(prompt.prompt_hash)}  v{prompt.version}  {state}"
        )
    created = sum(1 for prompt in published if prompt.created)
    typer.echo(f"{_count(created, 'version')} created, {len(published) - created} unchanged")
    # The URI, not a version id in a file: what comes back from the registry
    # reaches this line and nothing on disk (R14.5 row 3).
    typer.echo(f"published to MLflow: {tracking.uri}")
