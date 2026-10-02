"""`dossier run`: a pipeline over what the workspace holds, and its replay (specs 003-005)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from secrets import token_hex
from typing import Annotated

import typer

from dossier.application.convert import convert_source
from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.plan import Plan, build_plan, pinned_documents
from dossier.application.run import (
    MissingFromReplay,
    RunInputs,
    RunRecording,
    execute,
    key_hashes,
    recorded_failures,
    replay,
    replayed_inputs,
    replayed_parts,
)
from dossier.cli import bootstrap
from dossier.cli.convert import exit_if_unconvertible, read_holdings
from dossier.config.environment import environment
from dossier.config.load import ConfigError, load_output_schemas, load_pipeline, load_sources
from dossier.domain.concurrency import concurrency as concurrency_setting
from dossier.domain.conversion import (
    PART_SUFFIX,
    PART_TYPE,
    NoConverter,
    is_container,
    is_read,
    part_name,
    unpack_parts,
)
from dossier.domain.conversion import used as used_converters
from dossier.domain.hashing import text_hash
from dossier.domain.pipeline import PipelineConfig, SourceConfig
from dossier.domain.plan import check_tried
from dossier.domain.ports import ImagePart
from dossier.domain.resolution import PinnedConverter, check_kinds, moved_since, run_id
from dossier.domain.store import RUNS_ROOT, TRIES_ROOT, replay_path, try_path
from dossier.domain.sync import DocumentCollision, State, one_document_per_key
from dossier.domain.tracking import NAMESPACE, failure_line, label_for, step_line
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.connectors.registry import declared_keys
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.models.registry import available_providers
from dossier.infrastructure.store import SnapshotStore

# The pairs `dossier run` refuses, and why each cannot be both (R4.26).
_EXCLUSIVE = (
    ("--doc", "--plan", "a plan compares a full run with the last one"),
    ("--doc", "--replay", "a replay reproduces a whole run"),
    ("--plan", "--replay", "a replay reproduces a past run and plans nothing"),
)


def run(
    ctx: typer.Context,
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
    concurrency: str | None = typer.Option(
        None,
        "--concurrency",
        help="How many of a step's documents to ask about at once (R9.19). "
        "Default: DOSSIER_CONCURRENCY, else 1.",
        metavar="N",
    ),
    # Annotated, because a list default is mutable and B008 refuses it there.
    tried: Annotated[
        list[str] | None,
        typer.Option(
            "--doc",
            help="Ask only about this document; repeat for more. A try, not a run (R4.18).",
            metavar="KEY",
        ),
    ] = None,
) -> None:
    """Execute a pipeline, report what executing it would do, or replay one (spec 004).

    `pipeline` is optional with `--replay`, because a replay reads the pipeline
    name from the manifest and consults no configuration at all (R4.7). Requiring
    it made spec 004's own documented invocation --
    `dossier run --replay runs/<run_id>/` -- fail on a missing argument that was
    then ignored.
    """
    # Each of the three makes this a different command, and two cannot both be
    # done. Doing one and ignoring the other printed a success for a command
    # nobody typed, so the pair stops here, before anything is read (R4.26).
    given = {"--plan": plan, "--replay": bool(replay_from), "--doc": bool(tried)}
    for flag, other, why in _EXCLUSIVE:
        if given[flag] and given[other]:
            typer.echo(f"{flag} cannot be combined with {other}: {why}", err=True)
            raise typer.Exit(code=2)

    # A run, a try and a replay all write the workspace; a plan writes nothing,
    # and runs beside whatever does (R20.1).
    if not plan:
        bootstrap.hold_workspace(ctx, Path.cwd(), "run")

    if replay_from:
        _replay(Path.cwd(), Path(replay_from))
        return

    if not pipeline:
        typer.echo("a pipeline name is required unless --replay is given", err=True)
        raise typer.Exit(code=2)

    if not plan:
        _execute(
            Path.cwd(),
            pipeline,
            label=label,
            concurrency=concurrency,
            tried=tuple(tried) if tried else None,
        )
        return

    workspace = Path.cwd()

    try:
        path = bootstrap.pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
        declared = {
            source.id: source
            for source in load_sources(workspace / "sources.yaml", connectors=declared_keys())
        }
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    # What the run refuses from the configuration alone, the plan refuses too:
    # a plan promising a step the run will not take is R4.12 broken (R4.13).
    _check_kinds_or_stop(pipeline, config, declared)

    documents: dict[str, str] = {}
    # Pinned apart, as the run pins them, or the plan would compare a
    # procedure against a manifest that holds it as context (R4.16, R4.17).
    reference: dict[str, str] = {}
    # The same requests a run would make of the converters, so the plan pins the
    # same set the run will (R8.9) -- otherwise a plugin the corpus never needed
    # would print `converters changed` against a manifest that never named it.
    requests: list[tuple[str, Sequence[str] | None]] = []
    available = bootstrap.converters_for(workspace)
    try:
        with Ledger(workspace) as ledger:
            for name in config.synced_sources:
                if name not in declared:
                    continue
                convert = declared[name].convert
                # Only what the run will read: a document left out (R8.27), or
                # one nothing converts by default (R8.25), is pinned by no run,
                # and counting it here promised a step the run then served from
                # cache (R4.12).
                rows = [
                    row
                    for row in ledger.rows(name)
                    if row.state is State.TOMBSTONED
                    or is_read(media_type=row.media_type, kinds=convert, available=available)
                ]
                if name in config.sources:
                    documents.update(pinned_documents(rows))
                if name in config.reference:
                    reference.update(pinned_documents(rows))
                requests.extend(
                    (row.media_type, convert)
                    for row in rows
                    if row.state is not State.TOMBSTONED
                )
    except NoConverter as error:
        # A declared pair nothing claims, or two claimants: the run would stop
        # before anything converts (R8.24), so the plan stops here with it.
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    # The latest run that finished: one that stopped wrote its manifest
    # before it asked anything, and `cached` against it is a promise its
    # cache may not keep (R4.31).
    previous, previous_id = bootstrap.latest_run(workspace, pipeline, finished=True)

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

    # What the run compared against failed: never cached, so asked again (R4.32).
    failed: dict[str, list[str]] = {}
    if previous_id is not None:
        for entry in recorded_failures(workspace / RUNS_ROOT / previous_id) or ():
            failed.setdefault(str(entry["step"]), []).append(str(entry["document"]))

    try:
        report = build_plan(
            pipeline=config,
            pipeline_hash=text_hash(path),
            documents=documents,
            reference=reference,
            previous=previous,
            previous_id=previous_id,
            prompt_hashes=prompt_hashes,
            schema_hashes=schema_hashes,
            failed=failed,
            # Read here, as the run reads them, because a raised converter
            # version changes the text every step reads and therefore every key
            # above it (R5.4). Listing entry points opens no file a plan may not
            # open and builds no client, so R4.6 is untouched.
            converters=[
                PinnedConverter(
                    id=c.id, version=c.version, media_type=c.media_type, kind=c.kind
                )
                for c in used_converters(requests=requests, available=available)
            ],
        )
    except ValueError as error:
        # Resolution failed, so nothing ran and nothing was written (R4.1).
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    for line in _plan_lines(report):
        typer.echo(line)


def _check_kinds_or_stop(
    pipeline: str, config: PipelineConfig, declared: Mapping[str, SourceConfig]
) -> None:
    """Stop, naming the step, if it reads a kind no source was told to make (R4.13)."""
    try:
        check_kinds(
            steps=config.steps,
            sources=[declared[name] for name in config.sources if name in declared],
            reference=[declared[name] for name in config.reference if name in declared],
        )
    except ValueError as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error


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
        if step.step.model is not None:
            # The model this step is asked with where it is not the header's
            # (R3.14): a `model changed` line otherwise leaves a person to work
            # out which of two models it means.
            lines.append(f"      model: {step.step.model}")
        if step.was is not None:
            lines.append(f"      was: [{', '.join(step.was)}]")
            lines.append(f"      now: [{', '.join(step.step.inputs)}]")
        if step.moved:
            lines.append(f"      moved: [{', '.join(step.moved)}]")

    lines.append(
        f"{report.rerunning} of {len(report.steps)} step(s) would run · nothing written"
    )
    return lines


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
            # What the run recorded as failed, reproduced rather than looked for
            # (R4.28). Absent for a run from before R4.27.
            failures=recorded_failures(directory),
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
    # Each failure the run reported, reported again as it was (R6.31). The exit
    # stays 0: the replay reproduced what it was asked to (R4.28).
    for step in report.steps:
        for result in step.failed:
            typer.echo(
                "    "
                + failure_line(step=step.step, document=result.document, reason=result.error),
                err=True,
            )


def _execute(
    workspace: Path,
    pipeline: str,
    *,
    label: str = "",
    concurrency: str | None = None,
    tried: Sequence[str] | None = None,
) -> None:
    """`dossier run <pipeline>` (spec 004, spec 005), or a try with `--doc` (R4.18)."""
    # Before any work: a value that is not a count is refused by where it came
    # from, not discovered as a run that asked one document at a time (R9.19).
    # A string, not an int, so `four` is refused in the same words as `0`.
    try:
        asked_at_once = concurrency_setting(environment(workspace), flag=concurrency)
    except ValueError as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    try:
        path = bootstrap.pipeline_path(workspace, pipeline)
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
    # came through here, but by then conversion has already run -- and R8.24
    # would report the same pipeline as an installation problem, which is the
    # other failure with the other fix.
    _check_kinds_or_stop(pipeline, config, declared)

    tracker, experiment = bootstrap.tracking_for(workspace, pipeline, kind="run")
    capture = bootstrap.capture_for(workspace, pipeline) if tracker is not None else "full"
    # On the same switch as the tracker: a version is part of the record,
    # and R10.1 is one decision about whether there is a record at all.
    versions = bootstrap.versions_for(workspace) if tracker is not None else None
    # Same switch, same reason (R14.7 row 3): with tracking off the registry
    # is not merely unlinked but unasked, because a run reaching a server it
    # was told not to use is the thing R10.1 decides.
    prompt_registry = bootstrap.prompt_registry_for(workspace) if tracker is not None else None

    store = SnapshotStore(workspace)
    converters = bootstrap.converters_for(workspace)
    text: dict[str, str] = {}
    # Every converted kind, not only `markdown`, so a step naming one can be
    # handed it (R3.11). A kind whose artifact is not text is absent from here
    # and reaches a step another way; this is what a prompt placeholder holds.
    content: dict[str, dict[str, str]] = {}
    # What the `reference:` sources hold, by kind: the context every call
    # reading `reference` is shown whole (R3.18).
    reference: dict[str, dict[str, str]] = {}
    # And the snapshot behind each, pinned so a replay shows the same (R4.16).
    reference_documents: dict[str, str] = {}
    parts: dict[str, dict[str, list[tuple[str, ImagePart]]]] = {}
    documents: dict[str, str] = {}
    media_types: dict[str, str] = {}
    by_source: dict[str, list[str]] = {}
    # What each held document asked of the converters, so the manifest can pin
    # the ones the run used rather than the ones this machine carries (R8.9).
    requests: list[tuple[str, Sequence[str] | None]] = []
    started_at = datetime.now(UTC)
    # Filed after any run already filed in the same second, so the latest by
    # name is the latest started (R0.15). A try is ordered among tries: it is
    # filed under `tries/`, and no reader of `runs/` sees it (R4.20).
    filed_under = workspace / (TRIES_ROOT if tried else RUNS_ROOT)
    this_run = run_id(
        started_at,
        token_hex(2),
        taken=[path.name for path in filed_under.iterdir()] if filed_under.is_dir() else [],
    )
    convert_cache = ArtifactCache(workspace, namespace="convert")
    unreadable: list[tuple[str, str, str]] = []

    with Ledger(workspace) as ledger:
        holdings = read_holdings(ledger, config.synced_sources, declared)
        exit_if_unconvertible(holdings, converters)
        for name, source, held in holdings:
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
            # A `reference:` source is context: shown to the calls that read it,
            # and never itself asked about, filed or scored (R3.17). Listed under
            # `sources:` as well, it is read both ways.
            audited = name in config.sources
            if name in config.reference:
                reference_documents.update(
                    {key: held[key].snapshot for key in converted.present}
                )
                media_types.update({key: held[key].media_type for key in converted.present})
            if audited:
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
                if decoded and name in config.reference:
                    reference.setdefault(kind, {}).update(decoded)
                if not audited:
                    continue
                if decoded:
                    content.setdefault(kind, {}).update(decoded)
                # A kind whose artifact is a container of parts, unpacked once
                # here so a per_part step can fan out over it (R3.12, R8.11).
                for key, payload in produced.items():
                    if not is_container(payload):
                        # Text, which reaches a step as a substitution (R8.11).
                        continue
                    try:
                        unpacked = unpack_parts(payload)
                    except ValueError as error:
                        # Begins as a container and cannot be read as one: a
                        # document that did not convert, named (R8.34).
                        unreadable.append(
                            (name, key, f"its {kind} container cannot be read: {error}")
                        )
                        continue
                    parts.setdefault(kind, {})[key] = [
                        (part_name(n, PART_SUFFIX), ImagePart(media_type=PART_TYPE, data=b))
                        for n, b in enumerate(unpacked, 1)
                    ]
            # Every document that converted, not only those that converted to
            # text. A source rendered to pictures alone would otherwise convert
            # successfully and then be absent from the run entirely (R6.15).
            if audited:
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

    # Every named document, before anything is asked about any (R4.19).
    if tried is not None:
        try:
            check_tried(tried, held=documents, sources=config.sources)
        except ValueError as error:
            typer.echo(f"{pipeline}: {error}", err=True)
            raise typer.Exit(code=2) from error

    # A new run resolves against what is held now, and says so when that is
    # not what the last run read: the one moment a person needs to know two
    # runs are not over the same evidence, before R7.8 refuses to compare them
    # (R4.9 row 4). Before any step runs, so the warning is read, not scrolled.
    previous, previous_id = bootstrap.latest_run(workspace, pipeline)
    if previous is not None:
        # The procedures too, marked as context: every call reading `reference`
        # is shown them, so a tightened one is evidence that moved (R4.9 row 5).
        # Named only by `--plan` and the manifest, it went unmentioned by the
        # run, until two runs were compared.
        listed = [
            f"{key} {how}" for key, how in moved_since(previous.documents, documents).items()
        ] + [
            f"{key} {how} (reference)"
            for key, how in moved_since(previous.reference, reference_documents).items()
        ]
        if listed:
            typer.echo(
                f"warning: the source has moved since run {previous_id}: {', '.join(listed)}"
            )

    try:
        report = execute(
            RunInputs(
                pipeline=config,
                pipeline_hash=text_hash(path),
                schemas=schemas,
                prompts=prompts,
                documents=documents,
                media_types=media_types,
                document_text=text,
                document_content=content,
                document_parts=parts,
                reference_content=reference,
                reference_documents=reference_documents,
                converters=[
                    PinnedConverter(
                        id=c.id, version=c.version, media_type=c.media_type, kind=c.kind
                    )
                    for c in used_converters(requests=requests, available=converters)
                ],
                source_configs=declared,
            ),
            workspace=workspace,
            model=bootstrap.BuiltOnFirstCall(config.model),
            models={
                own: bootstrap.BuiltOnFirstCall(own)
                for own in sorted(
                    {step.model for step in config.steps if step.model} - {config.model}
                )
            },
            cache=ArtifactCache(workspace, namespace="stage"),
            concurrency=asked_at_once,
            tried=tried,
            run_id=this_run,
            started_at=started_at,
            dossier_version=version("dossier"),
            recording=RunRecording(
                tracker=tracker,
                experiment=experiment,
                environ=environment(workspace),
                label=label_for(label, environment(workspace)),
                capture=capture,
                versions=versions,
                version_experiment=experiment or "",
                prompt_registry=prompt_registry,
                prompt_prefix=environment(workspace).get(NAMESPACE, ""),
            ),
        )
    except ValueError as error:
        # Resolution failed, so nothing ran and nothing was written (R4.1).
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error
    except bootstrap.MODEL_FAILURES as error:
        # The first cache miss needed a model this machine cannot reach, or the
        # endpoint refused. Named by variable, or by URL and status and never by
        # key (R9.2 row 3, R9.8 row 1); answers already cached stay cached.
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    for source, document, reason in unreadable:
        typer.echo(f"  {source}: {document} could not be converted: {reason}", err=True)

    if tried is None:
        typer.echo(f"run {report.run_id} · {report.manifest_path}")
    else:
        # Named as a try, where its files are: nothing under `runs/` (R4.20, R4.22).
        typer.echo(f"try {report.run_id} · {try_path(report.run_id)}/")
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
                tokens=step.tokens,
                unit=step.unit,
                skipped=step.skipped,
            )
        )
        for document, check in findings:
            # The detail `check_field` composed, verbatim. It already names the
            # field and says which rule was not met; repeating either here would
            # be this message deciding it knows better than the check did.
            typer.echo(f"    {document}  {check.detail}")

    for step in report.steps:
        for result in step.failed:
            typer.echo(
                "    "
                + failure_line(step=step.step, document=result.document, reason=result.error),
                err=True,
            )

    # Either kind of failure means this audit covered less than the corpus. A
    # zero exit here would let anything reading `$?` quote it as clean.
    if report.failed or unreadable:
        raise typer.Exit(code=1)
