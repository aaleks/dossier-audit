"""The `dossier` command line (specs 002, 003).

The only layer that exits the interpreter, and the only place that knows which
concrete connector, store and ledger are in play -- everything below takes them
as arguments.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from secrets import token_hex

import typer

from dossier.application.convert import (
    MARKDOWN as MARKDOWN_KIND,
)
from dossier.application.convert import (
    ConvertReport,
    HeldDocument,
    convert_source,
)
from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.plan import (
    Plan,
    build_plan,
    latest_manifest,
    pinned_documents,
)
from dossier.application.run import MissingFromReplay, execute, replay
from dossier.application.sync import SourceReport, sync_source
from dossier.config.load import ConfigError, load_pipeline, load_sources
from dossier.domain.conversion import NoConverter
from dossier.domain.hashing import text_hash
from dossier.domain.keys import ConvertInputs, cache_key
from dossier.domain.ports import ModelClient
from dossier.domain.resolution import PinnedConverter, run_id
from dossier.domain.sync import DocumentCollision, State, one_document_per_key
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.connectors.registry import UnknownSourceType, build_connector
from dossier.infrastructure.converters.registry import installed_converters
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

app = typer.Typer(add_completion=False)


@app.callback()
def main() -> None:
    """Collect documents, audit them, and prove the result.

    A callback is declared so that `sync` stays a sub-command. Typer collapses
    a single-command app into a bare invocation, and `dossier <pipeline>` is
    not the interface the specs describe -- `run` and `eval` join it later.
    """


@app.command()
def sync(pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/")) -> None:
    """Fetch only what changed for the sources a pipeline declares (R2.12)."""
    workspace = Path.cwd()
    started_at = datetime.now(UTC)

    try:
        config = load_pipeline(_pipeline_path(workspace, pipeline))
        declared = {source.id: source for source in load_sources(workspace / "sources.yaml")}
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    missing = [name for name in config.synced_sources if name not in declared]
    if missing:
        typer.echo(
            f"pipeline {pipeline!r} names sources not in sources.yaml: {missing}", err=True
        )
        raise typer.Exit(code=2)

    store = SnapshotStore(workspace)
    reports: list[SourceReport] = []

    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            source = declared[name]
            try:
                connector = build_connector(source, workspace=workspace)
            except (UnknownSourceType, ValueError) as error:
                typer.echo(str(error), err=True)
                raise typer.Exit(code=2) from error

            report = sync_source(
                config=source,
                connector=connector,
                store=store,
                ledger=ledger,
                now=started_at,
            )
            reports.append(report)
            typer.echo(_source_line(report))

    written = sum(report.snapshots_written for report in reports)
    tombstoned = sum(report.tombstoned for report in reports)
    typer.echo(f"ledger updated · {written} new snapshots · {tombstoned} tombstoned")

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


def _pipeline_path(workspace: Path, name: str) -> Path:
    path = workspace / "pipelines" / name / "pipeline.yaml"
    if not path.exists():
        # Naming where it looked matters more than naming what is missing: the
        # usual cause is being in the wrong directory (R2.12 example 3).
        raise ConfigError(f"no pipeline {name!r}: expected {path}")
    return path


def build_model_client(model_id: str) -> ModelClient:
    """Resolve a pinned model identifier to a client.

    Not implemented yet, and deliberately a named function rather than an inline
    construction: it is the seam the composition root hands to a use case, and
    R4.6 is the claim that `--plan` never reaches it. A test replaces this and
    asserts it was never called.
    """
    raise NotImplementedError(
        f"no model client is wired up yet for {model_id!r}. "
        "`--plan` does not need one; executing a run will."
    )


@app.command()
def run(
    pipeline: str = typer.Argument(
        "", help="Pipeline name under pipelines/. Not needed with --replay."
    ),
    plan: bool = typer.Option(False, "--plan", help="Report what would run. Do nothing."),
    replay_from: str = typer.Option(
        "", "--replay", help="Reproduce a past run from runs/<run_id>/", metavar="DIR"
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
        _execute(Path.cwd(), pipeline)
        return

    workspace = Path.cwd()

    try:
        path = _pipeline_path(workspace, pipeline)
        config = load_pipeline(path)
        declared = {source.id: source for source in load_sources(workspace / "sources.yaml")}
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    documents: dict[str, str] = {}
    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            if name in declared:
                documents.update(pinned_documents(ledger.rows(name)))

    previous, previous_id = latest_manifest(workspace / "runs", pipeline)

    try:
        report = build_plan(
            pipeline=config,
            pipeline_hash=text_hash(path),
            documents=documents,
            previous=previous,
            previous_id=previous_id,
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
    silently re-points every relative reference below it (R4.5).
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

    lines.append(
        f"{report.rerunning} of {len(report.steps)} step(s) would run · nothing written"
    )
    return lines


@app.command()
def convert(pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/")) -> None:
    """Convert what a pipeline needs, and report what that cost (R8.8).

    Optional: `run` converts what it needs anyway, and conversion is idempotent
    and cached, so running this early costs nothing. It exists so the text a
    stage will actually see can be inspected before a single model call is made
    -- which on a PDF-heavy corpus is usually where the surprises are.
    """
    workspace = Path.cwd()

    try:
        config = load_pipeline(_pipeline_path(workspace, pipeline))
        declared = {source.id: source for source in load_sources(workspace / "sources.yaml")}
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

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
                row.key: HeldDocument(snapshot=row.content_hash, media_type=row.media_type)
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

    for report in reports:
        typer.echo(_convert_line(report))
        for failure in report.failed:
            typer.echo(f"    {failure.document}: {failure.error}")

    converted = sum(report.converted for report in reports)
    cached = sum(report.cached for report in reports)
    typer.echo(f"cache updated · {converted} converted · {cached} cached")

    failed = [failure for report in reports for failure in report.failed]
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

    try:
        # The conversions this run produced, read back by their keys rather than
        # recomputed. A replay therefore needs no converter installed at all --
        # the same shape as needing no model client. Raising a converter version
        # is how R5.4 invalidates conversions, so re-converting would produce
        # text the original run never saw (R4.7, R4.9).
        _require_pinned_snapshots(manifest, SnapshotStore(workspace))
        text = _replayed_text(manifest, cache)
        report = replay(
            manifest=manifest,
            document_text=text,
            cache=ArtifactCache(workspace, namespace="stage"),
        )
    except MissingFromReplay as error:
        # A replay may fail; it may never substitute other content (R4.7 row 4).
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    typer.echo(f"replayed {manifest.run_id} · {manifest.plan.pipeline}")
    for step in report.steps:
        typer.echo(f"  {step.step}: {len(step.results)} artifact(s) from cache")
    typer.echo(f"{report.cache_hits} artifact(s) reproduced · no model calls")


def _execute(workspace: Path, pipeline: str) -> None:
    """`dossier run <pipeline>` (spec 004, spec 005)."""
    try:
        path = _pipeline_path(workspace, pipeline)
        config = load_pipeline(path)
        declared = {source.id: source for source in load_sources(workspace / "sources.yaml")}
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    store = SnapshotStore(workspace)
    converters = installed_converters()
    text: dict[str, str] = {}
    documents: dict[str, str] = {}
    media_types: dict[str, str] = {}
    by_source: dict[str, list[str]] = {}
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
                row.key: HeldDocument(snapshot=row.content_hash, media_type=row.media_type)
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
            by_source[name] = sorted(converted.text)
            text.update(converted.text)
            documents.update({key: held[key].snapshot for key in converted.text})
            media_types.update({key: held[key].media_type for key in converted.text})
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
    schemas = {
        step.id: json.loads((path.parent / step.output).read_text(encoding="utf-8"))
        for step in config.steps
        if step.output is not None
    }

    try:
        # Bound before the call rather than inside its argument list. Python
        # evaluates an argument before the function is entered, so constructing
        # the client there ran it ahead of resolution -- and a pipeline with both
        # a bad reference and an unreachable model reported the model (R4.1).
        one_document_per_key(by_source)
        model = build_model_client(config.model)
    except (DocumentCollision, NotImplementedError) as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    try:
        report = execute(
            workspace=workspace,
            pipeline=config,
            pipeline_hash=text_hash(path),
            documents=documents,
            media_types=media_types,
            document_text=text,
            schemas=schemas,
            prompts=prompts,
            model=model,
            cache=ArtifactCache(workspace, namespace="stage"),
            run_id=this_run,
            started_at=started_at,
            dossier_version=version("dossier"),
            converters=[
                PinnedConverter(
                    id=c.id, version=c.version, media_type=c.media_type, kind=c.kind
                )
                for c in converters
            ],
        )
    except ValueError as error:
        # Resolution failed, so nothing ran and nothing was written (R4.1).
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    for source, document, reason in unreadable:
        typer.echo(f"  {source}: {document} could not be converted: {reason}", err=True)

    typer.echo(f"run {report.run_id} · {report.manifest_path}")
    for step in report.steps:
        cached = len(step.served_from_cache)
        typer.echo(
            f"  {step.step}: {len(step.results)} document(s) · {cached} from cache · "
            f"{len(step.failed)} failed"
        )

    for step, document in report.failed:
        typer.echo(f"    {step} failed on {document}", err=True)

    # Either kind of failure means this audit covered less than the corpus. A
    # zero exit here would let anything reading `$?` quote it as clean.
    if report.failed or unreadable:
        raise typer.Exit(code=1)
def _converters_for(manifest: Manifest):
    """The converters a past run used, as its manifest recorded them.

    Not `installed_converters()`. Raising a converter's version is how R5.4
    invalidates conversions, so a replay that adopted today's version would
    convert the pinned snapshots into text the original run never saw, key
    every stage differently, and report the result as a missing cache artifact --
    naming neither the converter nor the version, and reading like a corrupted
    cache.

    An installed converter is matched by id *and* version, and a version the
    workspace no longer has is refused by name. A replay may fail; it may never
    substitute another tool's output for the one that was used (R4.7 row 4).
    """
    installed = {(c.id, c.version): c for c in installed_converters()}
    missing = [
        f"  {pinned.id} {pinned.version} (for {pinned.media_type} -> {pinned.kind})"
        for pinned in manifest.plan.converters
        if (pinned.id, pinned.version) not in installed
    ]
    if missing:
        raise MissingFromReplay(
            f"{manifest.run_id} used converters this workspace no longer has:\n"
            + "\n".join(missing)
            + "\nInstall them to reproduce this run. Nothing has been substituted."
        )
    return [installed[(pinned.id, pinned.version)] for pinned in manifest.plan.converters]


def _replayed_text(manifest: Manifest, cache: ArtifactCache) -> dict[str, str]:
    """The converted text a past run read, from the entries it wrote.

    Each key is recomposed from the manifest alone -- the snapshot the run
    pinned, and the id and version of the converter that claimed that document's
    media type. Nothing is read from the ledger, from `pipeline.yaml`, or from
    the converters installed today.

    A conversion whose entry is gone stops the replay by name. Re-deriving it
    would mean converting with whatever is installed now, which is precisely the
    substitution R4.7 row 4 forbids.
    """
    claimed = {(c.media_type, c.kind): c for c in manifest.plan.converters}
    text: dict[str, str] = {}
    missing: list[str] = []

    for document in manifest.plan.documents:
        converter = claimed.get((document.media_type, MARKDOWN_KIND))
        if converter is None:
            missing.append(
                f"  {document.key}: no converter recorded for {document.media_type!r}"
            )
            continue

        key = cache_key(
            ConvertInputs(
                snapshot=document.snapshot,
                converter_id=converter.id,
                converter_version=converter.version,
            )
        )
        stored = cache.get(key)
        if stored is None:
            missing.append(
                f"  {document.key}: no cached conversion for snapshot "
                f"{document.snapshot[:12]}... by {converter.id} {converter.version}"
            )
            continue
        text[document.key] = stored.decode("utf-8")

    if missing:
        raise MissingFromReplay(
            f"{manifest.run_id} cannot be reproduced:\n"
            + "\n".join(missing)
            + "\nNothing has been substituted."
        )
    return text


def _require_pinned_snapshots(manifest: Manifest, store: SnapshotStore) -> None:
    """Every snapshot this run read must still be held (R4.7 row 4).

    Checked even though the conversions are served from cache and the bytes are
    not needed. A replay that succeeded while the documents it audited were gone
    would be reproducing a finding whose evidence no longer exists -- and R4.9's
    whole claim is that a past audit is defended by what it actually read.

    Snapshots are never deleted (R0.2), so a missing one means the workspace is
    damaged. Naming the hash is what makes that diagnosable rather than merely
    loud.
    """
    missing = [
        f"  {document.key}: no snapshot for {document.snapshot[:12]}..."
        for document in manifest.plan.documents
        if not store.exists(document.snapshot)
    ]
    if missing:
        raise MissingFromReplay(
            f"{manifest.run_id} pinned snapshots this workspace no longer holds:\n"
            + "\n".join(missing)
            + "\nNothing has been substituted."
        )
