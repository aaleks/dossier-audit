"""`dossier review pull` and `dossier review apply` (spec 015).

The one read `dossier` makes of what a person said in MLflow, and it is made
here and nowhere else: `build_review_source` lives in this module so the fence
R15.5 draws is one file wide.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from dossier.application.review import apply_candidates, pull_reviews
from dossier.cli import bootstrap
from dossier.config.environment import environment
from dossier.config.load import ConfigError, load_enum_values, load_fields, load_pipeline
from dossier.domain.ports import ReviewSource
from dossier.domain.review import CANDIDATES, FEEDBACK, review_report
from dossier.domain.scoring import FieldKind
from dossier.domain.tracking import TrackingSettings, experiment_name, namespace
from dossier.domain.tracking import settings as tracking_settings
from dossier.infrastructure.models.registry import available_providers
from dossier.infrastructure.tracking.mlflow import TrackingUnavailable, connect_reviews

review_app = typer.Typer(
    add_completion=False,
    help="Bring reviewers' verdicts on a pipeline's runs back from MLflow (spec 015).",
)


def build_review_source(settings: TrackingSettings) -> ReviewSource:
    """Where reviewers' verdicts are read back from, checked before anything is read.

    The seam a test replaces with a `FakeReviewSource`, as `build_dataset_registry`
    is. Built by `dossier review pull` and by no other command: it is the one
    read `dossier` makes of what a person said in MLflow, and it reaches the
    files under `review/` and nothing else (R15.5).
    """
    return connect_reviews(settings.uri, auth=settings.auth, ca_bundle=settings.ca_bundle)


@review_app.command("pull")
def review_pull(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
) -> None:
    """Write every verdict reviewers left on a pipeline's runs to review/<pipeline>/ (R15.3).

    Reads the pipeline's run experiment and nothing else. Asks no model, and
    changes no key, manifest, artifact or gold file: what a reviewer expected
    becomes gold only through `dossier review apply` (R15.4, R15.5).
    """
    workspace = Path.cwd()
    environ = environment(workspace)

    try:
        bootstrap.pipeline_path(workspace, pipeline)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    # Tracking off is a refusal, as for `dataset publish`: the verdicts are on
    # the server and nowhere else, so there is nothing to do without it (R15.3
    # row 6). The server is reached here, before anything is read (R10.5).
    try:
        tracking = tracking_settings(environ)
        if tracking is None:
            raise ValueError(
                "pulling reviews needs tracking on: set DOSSIER_MLFLOW_ENABLED=true and "
                "DOSSIER_MLFLOW_TRACKING_URI. Reviewers' verdicts are read from MLflow "
                "and nowhere else"
            )
        experiment = experiment_name(kind="run", pipeline=pipeline, gold="", environ=environ)
        namespace(environ)
        source = build_review_source(tracking)
    except (ValueError, TrackingUnavailable) as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    verdicts = pull_reviews(
        source, experiment=experiment, directory=workspace / "review" / pipeline
    )
    if not verdicts:
        typer.echo(f"no reviewer verdicts on {pipeline}'s runs")
        return

    runs = len({verdict.run for verdict in verdicts})
    typer.echo(
        f"{pipeline}  {bootstrap.count(len(verdicts), 'verdict')} "
        f"on {bootstrap.count(runs, 'run')}"
    )
    for line in review_report(verdicts):
        typer.echo(f"  {line}")
    typer.echo(f"written to review/{pipeline}/{FEEDBACK}")
    expected = sum(1 for verdict in verdicts if verdict.kind == "expectation")
    if expected:
        # What a maintainer reads next, and applies with `dossier review apply`.
        typer.echo(
            f"{bootstrap.count(expected, 'expected value')} written as gold candidates to "
            f"review/{pipeline}/{CANDIDATES}"
        )


@review_app.command("apply")
def review_apply(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    gold: str = typer.Option(..., "--gold", help="Gold set directory", metavar="DIR"),
    verified_by: str = typer.Option(
        "", "--verified-by", help="Who signs these answers (R7.7).", metavar="NAME"
    ),
) -> None:
    """Make review/<pipeline>/candidates.jsonl gold, signed by --verified-by (R15.4).

    The file as the maintainer left it: a line deleted is a candidate rejected.
    Every candidate is checked before a gold file is written, and a refusal
    names each problem and writes nothing.
    """
    # Before anything is read. MLflow's trace view records every reviewer as
    # `User`, so the answer is signed by whoever applies it -- and there is no
    # anonymous path into the gold set (R7.7, R15.4 row 9).
    if not verified_by.strip():
        typer.echo(
            f"{pipeline}: --verified-by is required: there is no anonymous path into the gold "
            "set (R7.7). MLflow's trace view records every reviewer as User, so the "
            "maintainer who applies a candidate signs it",
            err=True,
        )
        raise typer.Exit(code=2)

    workspace = Path.cwd()
    try:
        path = bootstrap.pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
        kinds: dict[str, FieldKind] = {}
        allowed: dict[str, tuple[str, ...]] = {}
        for step in config.steps:
            if step.output:
                kinds.update(load_fields(path.parent / step.output))
                allowed.update(load_enum_values(path.parent / step.output))
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    candidates = workspace / "review" / pipeline / CANDIDATES
    if not candidates.is_file():
        typer.echo(
            f"{pipeline}: no candidates at review/{pipeline}/{CANDIDATES}; run "
            f"`dossier review pull {pipeline}` first",
            err=True,
        )
        raise typer.Exit(code=2)
    directory = workspace / gold
    if not directory.is_dir():
        typer.echo(f"{pipeline}: no gold set at {gold}", err=True)
        raise typer.Exit(code=2)

    try:
        applied = apply_candidates(
            candidates=candidates,
            gold=directory,
            kinds=kinds,
            allowed=allowed,
            verified_by=verified_by,
            today=datetime.now(UTC).date(),
        )
    except ValueError as error:
        typer.echo(f"{pipeline}: nothing applied:", err=True)
        for problem in getattr(error, "problems", [str(error)]):
            typer.echo(f"  {problem}", err=True)
        raise typer.Exit(code=2) from error

    if not applied:
        typer.echo("nothing to apply: every candidate is already gold")
        return
    for change in applied:
        before = repr(change.before) if change.had else "(new)"
        typer.echo(f"  {change.document}  {change.field}  {before} -> {change.after!r}")
    typer.echo(
        f"{bootstrap.count(len(applied), 'answer')} applied to {gold}, signed by {verified_by}"
    )
