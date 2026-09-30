"""`dossier status`: what the workspace holds, and what `eval` would withhold (spec 017).

It reads the ledger, `runs/` and a gold set, and changes none of them (R17.5).
It records nothing to MLflow, and so needs no server (R11.32).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dossier.application.status import read_runs
from dossier.cli import bootstrap
from dossier.cli.eval import has_per_part, judge_gate, refuse_unmeetable_gold, scored_step
from dossier.config.load import (
    ConfigError,
    load_fields,
    load_judge_rubrics,
    load_pipeline,
    load_sources,
)
from dossier.domain.grounding import judged_states
from dossier.domain.status import judged_lines, pipeline_lines, source_lines
from dossier.infrastructure.connectors.registry import declared_keys
from dossier.infrastructure.ledger import read_held
from dossier.infrastructure.models.registry import available_providers

PIPELINES_ROOT = "pipelines"


def status(
    pipeline: Annotated[
        str | None,
        typer.Argument(help="Narrow `pipelines` to this one; needed with --gold."),
    ] = None,
    gold: Annotated[
        str | None,
        typer.Option(
            "--gold",
            help="Say which judged fields `eval PIPELINE --gold DIR` would withhold (R17.4).",
            metavar="DIR",
        ),
    ] = None,
) -> None:
    """Say what each source holds, each pipeline's latest run, and what eval would withhold."""
    workspace = Path.cwd()
    if gold is not None and pipeline is None:
        # A gold set can serve several pipelines (R3.7), and a judge is checked
        # against one pipeline's rubrics and model: no pipeline, no one answer.
        typer.echo(
            f"--gold {gold} names a gold set, and one gold set can serve several "
            "pipelines (R3.7): name the pipeline its judges are checked for, as "
            f"`dossier status PIPELINE --gold {gold}`",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        sources = workspace / "sources.yaml"
        declared = (
            [source.id for source in load_sources(sources, connectors=declared_keys())]
            if sources.is_file()
            else []
        )
        if pipeline is not None:
            bootstrap.pipeline_path(workspace, pipeline)
        pipelines = [pipeline] if pipeline is not None else _pipelines(workspace)
        judged = judged_fields(workspace, pipeline, gold) if gold is not None else None
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    typer.echo("sources")
    for line in source_lines(declared, read_held(workspace)):
        typer.echo(f"  {line}")
    typer.echo("pipelines")
    for line in pipeline_lines(pipelines, read_runs(workspace)):
        typer.echo(f"  {line}")
    if judged is not None:
        typer.echo(f"judged fields · {pipeline} against {gold}")
        for line in judged:
            typer.echo(f"  {line}")


def judged_fields(workspace: Path, pipeline: str, gold: str) -> list[str]:
    """Each judged field of `pipeline`'s output, as `eval` would gate it (R17.4).

    The gate is `eval`'s own, asked with what `eval` asks it with: the
    pipeline's model, and every grounding state the pipeline can answer in. A
    pipeline or gold set `eval` would refuse before scoring is refused here, in
    its words: to answer from one of two outputs is the guess `eval` refuses,
    and a field of a gold set it refuses is never reached (R17.6).
    """
    path = bootstrap.pipeline_path(workspace, pipeline)
    config = load_pipeline(path, providers=available_providers())
    declaration = path.parent / scored_step(pipeline, config).output
    refuse_unmeetable_gold(pipeline, workspace / gold, load_fields(declaration))
    rubrics = load_judge_rubrics(declaration)
    _, withheld = judge_gate(
        workspace / gold,
        declaration,
        path.parent,
        config.model,
        states=judged_states(per_part=has_per_part(config)),
    )
    return judged_lines(sorted(rubrics), withheld)


def _pipelines(workspace: Path) -> list[str]:
    root = workspace / PIPELINES_ROOT
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if (path / "pipeline.yaml").is_file())
