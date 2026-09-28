"""`dossier prompts publish` (spec 014)."""

from __future__ import annotations

from pathlib import Path

import typer

from dossier.application.prompts import publish_prompts
from dossier.cli import bootstrap
from dossier.config.environment import environment
from dossier.config.load import ConfigError, load_judge_rubrics, load_pipeline
from dossier.domain.hashing import short
from dossier.domain.tracking import namespace
from dossier.domain.tracking import settings as tracking_settings
from dossier.infrastructure.models.registry import available_providers
from dossier.infrastructure.tracking.mlflow import TrackingUnavailable

prompts_app = typer.Typer(
    add_completion=False,
    help="Publish a pipeline's prompts to MLflow's prompt registry (spec 014).",
)


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
        path = bootstrap.pipeline_path(workspace, pipeline)
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
        registry = bootstrap.build_prompt_registry(tracking)
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
            registry, config=config, directory=directory, rubrics=rubrics, prefix=chosen
        )
    except (ConfigError, ValueError) as error:
        # The illegal pipeline name lands here (R14.1 row 5): composed, refused,
        # and nothing sent -- rather than an MLflow traceback partway through.
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(f"{config.name} · {bootstrap.count(len(published), 'prompt')}")
    width = max((len(prompt.name) for prompt in published), default=0)
    for prompt in published:
        state = "created" if prompt.created else "unchanged"
        typer.echo(
            f"  {prompt.name:<{width}}  {short(prompt.prompt_hash)}  v{prompt.version}  {state}"
        )
    created = sum(1 for prompt in published if prompt.created)
    typer.echo(
        f"{bootstrap.count(created, 'version')} created, {len(published) - created} unchanged"
    )
    # The URI, not a version id in a file: what comes back from the registry
    # reaches this line and nothing on disk (R14.5 row 3).
    typer.echo(f"published to MLflow: {tracking.uri}")
