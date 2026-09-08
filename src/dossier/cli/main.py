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

from dossier.application.convert import ConvertReport, HeldDocument, convert_source
from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.plan import (
    StepStatus,
    build_plan,
    latest_manifest,
    pinned_documents,
)
from dossier.application.run import MissingFromReplay, execute, replay
from dossier.application.sync import SourceReport, sync_source
from dossier.config.load import ConfigError, load_pipeline, load_sources
from dossier.domain.conversion import NoConverter
from dossier.domain.hashing import content_hash
from dossier.domain.sync import State
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


def build_model_client(model_id: str):
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
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    plan: bool = typer.Option(False, "--plan", help="Report what would run. Do nothing."),
    replay_from: str = typer.Option(
        "", "--replay", help="Reproduce a past run from runs/<run_id>/", metavar="DIR"
    ),
) -> None:
    """Execute a pipeline, report what executing it would do, or replay one (spec 004)."""
    if replay_from:
        _replay(Path.cwd(), Path(replay_from), pipeline)
        return

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
            pipeline_hash=content_hash(path.read_bytes()),
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


def _plan_lines(report) -> list[str]:
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
        marker = " " if step.status is StepStatus.CACHED else "!"
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


def _replay(workspace: Path, directory: Path, pipeline: str) -> None:
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
    converters = installed_converters()
    store = SnapshotStore(workspace)
    cache = ArtifactCache(workspace, namespace="convert")

    try:
        # Converted from the snapshots this run pinned, not from what the ledger
        # holds today. A source that has moved on, or been tombstoned, does not
        # change what this run read (R4.9).
        pinned = {
            document.key: HeldDocument(snapshot=document.snapshot, media_type=_media_type(
                workspace, document.key
            ))
            for document in manifest.plan.documents
        }
        converted = convert_source(
            source_id=manifest.plan.pipeline,
            documents=pinned,
            kinds=None,
            converters=converters,
            store=store,
            cache=cache,
        )
        report = replay(
            manifest=manifest,
            document_text=converted.text,
            cache=ArtifactCache(workspace, namespace="stage"),
        )
    except (MissingFromReplay, FileNotFoundError, NoConverter) as error:
        # A replay may fail; it may never substitute other content (R4.7 row 4).
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    typer.echo(f"replayed {manifest.run_id} · {manifest.plan.pipeline}")
    for step in report.steps:
        typer.echo(f"  {step.step}: {len(step.results)} artifact(s) from cache")
    typer.echo(f"{report.cache_hits} artifact(s) reproduced · no model calls")


def _media_type(workspace: Path, key: str) -> str:
    """What the ledger recorded for this document (R2.16).

    A replay reads the type from the ledger rather than from the manifest because
    it is a property of the bytes, not of the run -- the same snapshot has the
    same media type whenever it is read.
    """
    with Ledger(workspace) as ledger:
        for source in ledger.sources():
            row = ledger.row(source, key)
            if row is not None:
                return row.media_type
    raise MissingFromReplay(
        f"no ledger row for {key!r}; its media type is unknown and a replay may "
        "not guess one."
    )


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
                    cache=ArtifactCache(workspace, namespace="convert"),
                )
            except NoConverter as error:
                typer.echo(str(error), err=True)
                raise typer.Exit(code=2) from error
            text.update(converted.text)
            documents.update(
                {key: held[key].snapshot for key in converted.text}
            )

    started_at = datetime.now(UTC)
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
        report = execute(
            workspace=workspace,
            pipeline=config,
            pipeline_hash=content_hash(path.read_bytes()),
            documents=documents,
            document_text=text,
            schemas=schemas,
            prompts=prompts,
            model=build_model_client(config.model),
            cache=ArtifactCache(workspace, namespace="stage"),
            run_id=_run_id(started_at),
            started_at=started_at,
            dossier_version=version("dossier"),
        )
    except ValueError as error:
        # Resolution failed, so nothing ran and nothing was written (R4.1).
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(f"run {report.run_id} · {report.manifest_path}")
    for step in report.steps:
        cached = len(step.served_from_cache)
        typer.echo(
            f"  {step.step}: {len(step.results)} document(s) · {cached} from cache · "
            f"{len(step.failed)} failed"
        )

    for step, document in report.failed:
        typer.echo(f"    {step} failed on {document}", err=True)
    if report.failed:
        raise typer.Exit(code=1)


def _run_id(started_at: datetime) -> str:
    """A sortable, filesystem-legal identifier for one run (R0.8).

    ISO 8601 *basic* format: a run id is a directory name, and the extended
    form's colons are illegal on Windows. The suffix distinguishes two runs
    started in the same second.
    """
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{token_hex(2)}"
