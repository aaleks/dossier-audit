"""`dossier search INDEX QUERY`: the documents an index holds that answer a query (spec 019).

Everything a person can get wrong is refused before the model is asked: the
declaration (R18.10), a `--where` the index does not carry (R19.4), a reader
no source declares (R19.5), the connection string. Then the index is asked
which model it holds (R19.6), and only then is the query embedded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from dossier.application.search import SearchRefused, SearchReport, search_index
from dossier.cli import bootstrap
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
from dossier.domain.index import carried_output, document_id
from dossier.domain.search import (
    UnfilterableWhere,
    excerpt,
    header,
    reader_refusal,
    unreflected_line,
    values_line,
    wheres,
)
from dossier.domain.sync import State
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.connectors.registry import declared_keys
from dossier.infrastructure.index import IndexSinkFailed
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.models.openai_compatible import ModelRequestFailed
from dossier.infrastructure.models.registry import (
    UnknownProvider,
    available_embedding_providers,
    available_providers,
)


def search(
    index: Annotated[str, typer.Argument(help="An index declared as indexes/<INDEX>.yaml")],
    query: Annotated[str, typer.Argument(help="What to look for, in plain words")],
    limit: Annotated[
        int,
        typer.Option("--limit", help="How many documents, or chunks, to list.", min=1),
    ] = 10,
    where: Annotated[
        list[str] | None,
        typer.Option(
            "--where",
            help="Keep the documents carrying FIELD=VALUE; repeatable (R19.4).",
            metavar="FIELD=VALUE",
        ),
    ] = None,
    reader: Annotated[
        str | None,
        typer.Option("--as", help="Keep what READER may read (R19.5).", metavar="READER"),
    ] = None,
    chunks: Annotated[
        bool, typer.Option("--chunks", help="List chunks rather than documents (R19.2).")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the results as JSON (R19.8).")
    ] = False,
) -> None:
    """List the documents of an index that answer a query, best first."""
    workspace = Path.cwd()
    try:
        sources = load_sources(workspace / "sources.yaml", connectors=declared_keys())
        declaration = load_index(
            workspace / INDEXES / f"{index}.yaml",
            providers=available_providers(),
            sources=sources,
            embedding_providers=available_embedding_providers(),
        )
        path = bootstrap.pipeline_path(workspace, declaration.pipeline)
        pipeline = load_pipeline(path, providers=available_providers())
        enums = None
        if declaration.fields.carried:
            step = carried_output(pipeline.steps, pipeline=declaration.pipeline)
            enums = load_enum_values(path.parent / step.output)
        asked = wheres(where or [], index=index, filters=declaration.fields.filter, enums=enums)
        read_by = {
            name
            for source in sources
            if source.id in pipeline.sources
            for name in (source.acl or ())
        }
        refused = reader_refusal(reader, declared=read_by, pipeline=declaration.pipeline)
        if refused is not None:
            raise UnfilterableWhere(refused)
        dsn = index_dsn(declaration.target.dsn_env, index=index, environ=environment(workspace))
        embedder = bootstrap.build_embedding_provider(declaration.embedding_model)
        searched = bootstrap.build_index_search(dsn)
    except (ConfigError, UnfilterableWhere, UnknownProvider, IndexSinkFailed) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    try:
        report = search_index(
            declaration=declaration,
            query=query,
            where=asked,
            reader=reader,
            limit=limit,
            chunks=chunks,
            embedder=embedder,
            vectors=ArtifactCache(workspace, namespace="embed"),
            index=searched,
            held=_held(workspace, pipeline.sources),
        )
    except SearchRefused as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    except (ModelRequestFailed, IndexSinkFailed) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    if as_json:
        typer.echo(json.dumps(as_document(report), ensure_ascii=False, indent=2))
        return
    for line in printed(report):
        typer.echo(line)


def _held(workspace: Path, sources: list[str]) -> dict[str, str]:
    """Each document the ledger holds active for the pipeline, by id, with its snapshot."""
    with Ledger(workspace) as ledger:
        return {
            document_id(source, row.key): row.content_hash
            for source in sources
            for row in ledger.rows(source)
            if row.state == State.ACTIVE
        }


def printed(report: SearchReport) -> list[str]:
    """The lines a search prints: what was found and as whom, each result, then what the
    index does not reflect (R19.5, R19.7, R19.8)."""
    lines = [
        header(
            report.index, found=len(report.found), reader=report.reader, chunks=report.chunks
        )
    ]
    if not report.found:
        lines.append(f"no {'chunks' if report.chunks else 'documents'} found")
    for found in report.found:
        candidate, document = found.ranked.candidate, found.document
        key = document.document_id.split(":", 1)[-1]
        lines.append(f"{found.rank}. {key} · {document.title}")
        where = " > ".join(candidate.heading_path) if candidate.heading_path else document.title
        lines.append(f"   {where}{'  (record)' if candidate.kind == 'record' else ''}")
        lines.append(f"   {excerpt(candidate.text)}")
        values = values_line(document.values)
        if values is not None:
            lines.append(f"   {values}")
    stale = unreflected_line(report.index, report.unreflected)
    if stale is not None:
        lines.append(stale)
    return lines


def as_document(report: SearchReport) -> dict[str, object]:
    """The same results as JSON, for a script (R19.8 row 2)."""
    return {
        "index": report.index,
        "query": report.query,
        "reader": report.reader,
        "results": [
            {
                "rank": found.rank,
                "document_id": found.document.document_id,
                "title": found.document.title,
                "values": dict(found.document.values),
                "chunk_id": found.ranked.candidate.chunk_id,
                "kind": found.ranked.candidate.kind,
                "heading_path": list(found.ranked.candidate.heading_path),
                "text": found.ranked.candidate.text,
                "score": found.ranked.score,
                "meaning_rank": found.ranked.meaning,
                "words_rank": found.ranked.words,
            }
            for found in report.found
        ],
        "unreflected": report.unreflected,
    }
