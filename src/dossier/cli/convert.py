"""`dossier convert` (spec 008), and what every converting command reads the same way."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import typer

from dossier.application.convert import (
    ConvertReport,
    HeldDocument,
    convert_source,
    refuse_unconvertible,
)
from dossier.cli import bootstrap
from dossier.config.environment import environment
from dossier.config.load import ConfigError, load_pipeline, load_sources
from dossier.domain.conversion import NoConverter
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import Converter
from dossier.domain.sync import State
from dossier.domain.tracking import convert_description, count_metrics, label_for, run_name
from dossier.domain.tracking import tags as tracking_tags
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.connectors.registry import declared_keys
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.models.registry import available_providers
from dossier.infrastructure.store import SnapshotStore


def convert(
    ctx: typer.Context,
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
    bootstrap.hold_workspace(ctx, workspace, "convert")
    started_at = datetime.now(UTC)

    try:
        config = load_pipeline(
            bootstrap.pipeline_path(workspace, pipeline), providers=available_providers()
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
    tracker, experiment = bootstrap.tracking_for(workspace, pipeline, kind="convert")

    converters = bootstrap.converters_for(workspace)
    store = SnapshotStore(workspace)
    cache = ArtifactCache(workspace, namespace="convert")
    reports: list[ConvertReport] = []

    with Ledger(workspace) as ledger:
        holdings = read_holdings(ledger, config.synced_sources, declared)
        exit_if_unconvertible(holdings, converters)
        for name, source, held in holdings:
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
                # and the fix is an installation (R8.24).
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
                        "left_out": len(report.left_out),
                    },
                )
            )
        tracker.log_metrics(metrics)
        tracker.describe(convert_description(pipeline=pipeline, lines=printed))
        tracker.end_run(status="FAILED" if failed else "FINISHED")
        # Said where it was made, as `sync` says its own (R11.4 row 5).
        typer.echo(f"recorded to MLflow: {experiment}")

    if failed:
        # A failure is not zero work. Exiting zero here would make a run that
        # converted nothing indistinguishable from one that had nothing to do
        # (R8.6, R1.9's shape).
        raise typer.Exit(code=1)


def read_holdings(
    ledger: Ledger, names: Sequence[str], declared: Mapping[str, SourceConfig]
) -> list[tuple[str, SourceConfig, dict[str, HeldDocument]]]:
    """Each synced source's live documents, read once for both passes (R8.24)."""
    holdings = []
    for name in names:
        source = declared.get(name)
        if source is None:
            continue
        held = {
            row.key: HeldDocument(snapshot=row.snapshot, media_type=row.media_type)
            for row in ledger.rows(name)
            if row.state is not State.TOMBSTONED
        }
        holdings.append((name, source, held))
    return holdings


def exit_if_unconvertible(
    holdings: Sequence[tuple[str, SourceConfig, Mapping[str, HeldDocument]]],
    converters: Sequence[Converter],
) -> None:
    """Stop before anything converts, in any source, over a declared pair (R8.24).

    A configuration error, not a per-document one: the pipeline is not set up to
    read what it was pointed at, so nothing converts -- in the sources that could
    be read either -- and the fix is an installation or a `convert:` line.
    """
    try:
        refuse_unconvertible(
            [(held, source.convert) for _, source, held in holdings], converters=converters
        )
    except NoConverter as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error


def _convert_line(report: ConvertReport) -> str:
    """One line per source, in the shape sync already uses (R2.13, R8.8)."""
    line = (
        f"{report.source_id}  {report.held} held · {report.converted} converted · "
        f"{report.cached} cached"
    )
    if report.failed:
        line = f"{line} · {len(report.failed)} failed"
    # Counted apart from the failures: a source said it does not read these
    # (R8.27), and the choice should show wherever the counts do.
    return line if not report.left_out else f"{line} · {len(report.left_out)} left out"
