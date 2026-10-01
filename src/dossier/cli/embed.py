"""`dossier embed INDEX`: a pipeline's documents into its embedding index (spec 018).

Everything is loaded and checked before anything is converted, embedded or
written: the sources and who may read them (R18.6), the declaration (R18.10),
the connection string (R18.7 row 3) and the chunker. Then the documents the
ledger holds active are converted as a run converts them, and handed over.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dossier.application.convert import convert_source
from dossier.application.embed import ToIndex, embed_index, read_latest_run
from dossier.cli import bootstrap
from dossier.cli.convert import exit_if_unconvertible, read_holdings
from dossier.config.endpoints import index_dsn
from dossier.config.environment import environment
from dossier.config.load import (
    INDEXES,
    ConfigError,
    load_enum_values,
    load_index,
    load_pipeline,
    load_sources,
)
from dossier.domain.conversion import NoConverter
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.chunkers.registry import UnknownChunker, chunker_for
from dossier.infrastructure.connectors.registry import declared_keys
from dossier.infrastructure.index import IndexSinkFailed
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.models.openai_compatible import ModelRequestFailed
from dossier.infrastructure.models.registry import UnknownProvider, available_providers
from dossier.infrastructure.store import SnapshotStore


def embed(
    index: Annotated[str, typer.Argument(help="An index declared as indexes/<INDEX>.yaml")],
) -> None:
    """Write a pipeline's documents into its index, asking only for missing vectors."""
    workspace = Path.cwd()
    try:
        sources = load_sources(workspace / "sources.yaml", connectors=declared_keys())
        declaration = load_index(
            workspace / INDEXES / f"{index}.yaml",
            providers=available_providers(),
            sources=sources,
        )
        # Before anything is converted or embedded: an index nobody can write
        # to is found now, not after the model has been asked (R18.7 row 3).
        dsn = index_dsn(declaration.target.dsn_env, index=index, environ=environment(workspace))
        chunker = chunker_for(declaration.chunker)
        path = bootstrap.pipeline_path(workspace, declaration.pipeline)
        pipeline = load_pipeline(path, providers=available_providers())
        run, enums = None, None
        if declaration.fields.filter or declaration.fields.embed:
            # The one step declaring an output: `load_index` refused any other
            # number, as `eval` does (R18.10 row 6).
            step = next(step for step in pipeline.steps if step.output is not None)
            enums = load_enum_values(path.parent / step.output)
            run = read_latest_run(workspace, declaration.pipeline, step.id)
        embedder = bootstrap.build_embedding_provider(declaration.embedding_model)
        sink = bootstrap.build_index_sink(dsn)
    except (ConfigError, UnknownChunker, UnknownProvider, IndexSinkFailed) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    declared = {source.id: source for source in sources}
    converters = bootstrap.converters_for(workspace)
    store = SnapshotStore(workspace)
    cache = ArtifactCache(workspace, namespace="convert")
    documents: list[ToIndex] = []
    with Ledger(workspace) as ledger:
        holdings = read_holdings(ledger, pipeline.sources, declared)
        exit_if_unconvertible(holdings, converters)
        for name, source, held in holdings:
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
            documents.extend(
                ToIndex(source_id=name, key=key, snapshot=held[key].snapshot, text=text)
                for key, text in sorted(report.text.items())
            )

    try:
        report = embed_index(
            declaration=declaration,
            documents=documents,
            readers={source.id: source.acl for source in sources if source.acl},
            chunker=chunker,
            embedder=embedder,
            vectors=ArtifactCache(workspace, namespace="embed"),
            sink=sink,
            run=run,
            enums=enums,
        )
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    except (ModelRequestFailed, IndexSinkFailed) as error:
        # Reached and failed: the model or the index answered with an error, or
        # did not answer. What was cached stays cached for the next embed.
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    for note in report.notes:
        typer.echo(note)
    typer.echo(report.line)
