"""`dossier search INDEX QUERY`: the documents an index holds that answer a query (spec 019).

Everything a person can get wrong is refused before the model is asked: the
declaration (R18.10), a `--where` the index does not carry (R19.4), a reader
no source declares or no reader at all (R19.10, R19.11), the connection
string. Then the index is asked which model it holds (R19.6), and only then is
the query embedded.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from dossier.application.masking import detected_in, mask_query
from dossier.application.relevance import (
    RelevanceReport,
    gold_hash,
    measure_search,
    record_relevance,
)
from dossier.application.search import (
    SearchRefused,
    SearchReport,
    record_search,
    search_index,
)
from dossier.cli import bootstrap
from dossier.config.endpoints import index_dsn
from dossier.config.environment import environment
from dossier.config.load import (
    INDEXES,
    ConfigError,
    load_enum_values,
    load_index,
    load_pipeline,
    load_relevance_gold,
    load_sources,
)
from dossier.domain.index import carried_output, document_id
from dossier.domain.masking import MaskerUnavailable
from dossier.domain.pipeline import PipelineConfig
from dossier.domain.relevance import WORDS, unreadable
from dossier.domain.search import (
    ReadersRefused,
    UnfilterableWhere,
    excerpt,
    header,
    masked_where_refusal,
    readers_for,
    unreflected_line,
    values_line,
    where_values,
    wheres,
)
from dossier.domain.sync import State
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.connectors.registry import declared_keys
from dossier.infrastructure.index import IndexSearchFailed
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.models.openai_compatible import ModelRequestFailed
from dossier.infrastructure.models.registry import (
    UnknownProvider,
    available_embedding_providers,
    available_providers,
)


def search(
    index: Annotated[str, typer.Argument(help="An index declared as indexes/<INDEX>.yaml")],
    query: Annotated[
        str, typer.Argument(help="What to look for, in plain words. Not with --gold.")
    ] = "",
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit", help="How many documents, or chunks, to list. Default 10.", min=1
        ),
    ] = None,
    where: Annotated[
        list[str] | None,
        typer.Option(
            "--where",
            help="Keep the documents carrying FIELD=VALUE; repeatable (R19.4).",
            metavar="FIELD=VALUE",
        ),
    ] = None,
    named: Annotated[
        list[str] | None,
        typer.Option(
            "--as",
            help="Keep what READER may read; repeatable, for any of them (R19.10).",
            metavar="READER",
        ),
    ] = None,
    all_readers: Annotated[
        bool,
        typer.Option("--all-readers", help="Search every chunk, whoever may read it (R19.11)."),
    ] = False,
    chunks: Annotated[
        bool, typer.Option("--chunks", help="List chunks rather than documents (R19.2).")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the results as JSON (R19.12).")
    ] = False,
    label: Annotated[
        str,
        typer.Option(
            "--label", help="A name for this record, in MLflow (R10.11).", metavar="NAME"
        ),
    ] = "",
    gold: Annotated[
        str,
        typer.Option(
            "--gold",
            help="Measure search against relevance gold: one YAML file per query (spec 022).",
            metavar="DIR",
        ),
    ] = "",
    candidates: Annotated[
        int | None,
        typer.Option(
            "--candidates",
            help="With --gold: ask each list for N chunks rather than 100 (R22.9).",
            metavar="N",
            min=1,
        ),
    ] = None,
    words: Annotated[
        str | None,
        typer.Option(
            "--words",
            help="With --gold: match all of the query's words, or any (R22.10).",
            metavar="all|any",
        ),
    ] = None,
) -> None:
    """List the documents of an index that answer a query, best first.

    With `--gold`, measure instead: each of the gold set's queries is searched
    as its readers, and nDCG@10 and recall@10 are printed (spec 022).
    """
    # A variant is a measurement's to ask: search keeps spec 019's depth and
    # words until the pilot's numbers decide (R22.9, R22.10).
    if words is not None and words not in WORDS:
        typer.echo("--words is all or any", err=True)
        raise typer.Exit(code=2)
    if not gold and candidates is not None:
        typer.echo(
            "--candidates needs --gold: it measures a variant, and search keeps 100", err=True
        )
        raise typer.Exit(code=2)
    if not gold and words is not None:
        typer.echo(
            "--words needs --gold: it measures a variant, and search requires every word",
            err=True,
        )
        raise typer.Exit(code=2)
    if gold:
        # Before anything is read: each would change what is measured, and
        # measuring something other than what was asked would print a number
        # nobody can compare (R22.8).
        given = (
            ("a query", bool(query), "the gold set's files are the queries"),
            ("--as", bool(named), "each query names its readers"),
            ("--all-readers", all_readers, "each query names its readers"),
            ("--where", bool(where), "it changes what is measured"),
            ("--chunks", chunks, "it changes what is measured"),
            ("--limit", limit is not None, "it changes what is measured"),
        )
        for option, present, why in given:
            if present:
                typer.echo(f"--gold cannot be combined with {option}: {why}", err=True)
                raise typer.Exit(code=2)
        _measure(
            Path.cwd(),
            index,
            Path(gold),
            as_json=as_json,
            label=label,
            candidates=candidates,
            words=words or "all",
        )
        return
    if not query:
        typer.echo("a query is required unless --gold is given", err=True)
        raise typer.Exit(code=2)
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
        # Before the filters are read: a value refused by field and type is
        # never printed back, sent or recorded (R21.26).
        _refuse_masked_where(declaration.pipeline, pipeline, path, where or [], index=index)
        asked = wheres(where or [], index=index, filters=declaration.fields.filter, enums=enums)
        read_by = {
            name
            for source in sources
            if source.id in pipeline.sources
            for name in (source.acl or ())
        }
        readers = readers_for(
            named or [],
            all_readers=all_readers,
            declared=read_by,
            pipeline=declaration.pipeline,
        )
        dsn = index_dsn(declaration.target.dsn_env, index=index, environ=environment(workspace))
        embedder = bootstrap.build_embedding_provider(declaration.embedding_model)
        searched = bootstrap.build_index_search(dsn)
    except (
        ConfigError,
        UnfilterableWhere,
        ReadersRefused,
        UnknownProvider,
        IndexSearchFailed,
    ) as error:
        # Refused before anything was asked: the driver missing is an install
        # to fix, named, as a declaration to fix is (R18.7 row 3).
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    # A masked index is searched with a masked query: nothing typed into it
    # reaches the model, the words searched, the terminal or MLflow (R21.19).
    query = _masked_query(declaration.pipeline, pipeline, path, query)

    # Before any work, as every command's: a server nobody can reach is refused
    # now, not after the model has been asked (R10.5, R11.35).
    tracker, experiment = bootstrap.tracking_for(workspace, declaration.pipeline, kind="search")

    try:
        report = search_index(
            declaration=declaration,
            query=query,
            where=asked,
            readers=readers,
            limit=10 if limit is None else limit,
            chunks=chunks,
            embedder=embedder,
            vectors=ArtifactCache(workspace, namespace="embed"),
            index=searched,
            held=_held(workspace, pipeline.sources),
        )
    except SearchRefused as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    except (ModelRequestFailed, IndexSearchFailed) as error:
        # Reached and failed: the model or the index answered with an error, or
        # did not answer. A query vector already asked for stays cached.
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    if as_json:
        typer.echo(json.dumps(as_document(report), ensure_ascii=False, indent=2))
    else:
        for line in printed(report):
            typer.echo(line)
    if tracker is not None:
        record_search(
            tracker,
            experiment=experiment or "",
            report=report,
            where=asked,
            pipeline=declaration.pipeline,
            environ=environment(workspace),
            label=label,
        )
        # On stderr: stdout is the results, and with --json nothing else (R19.12
        # row 2).
        typer.echo(f"recorded to MLflow: {experiment}", err=True)


def _measure(
    workspace: Path,
    index: str,
    gold: Path,
    *,
    as_json: bool,
    label: str,
    candidates: int | None,
    words: str,
) -> None:
    """`dossier search INDEX --gold DIR`: each query searched as its readers, and measured."""
    started = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
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
        # Every file read before any is refused (R22.5).
        queries = load_relevance_gold(gold if gold.is_absolute() else workspace / gold)
        acl = {source.id: tuple(source.acl or ()) for source in sources}
        # A judgment no reader of its query may read is a miss the search was
        # right to make: refused before any search, naming each (R22.6).
        lines = unreadable(queries, acl)
        if lines:
            raise ConfigError("\n".join(lines))
        read_by = {
            name
            for source in sources
            if source.id in pipeline.sources
            for name in (source.acl or ())
        }
        readers = {
            query.name: readers_for(
                list(query.readers),
                all_readers=False,
                declared=read_by,
                pipeline=declaration.pipeline,
            )
            for query in queries
        }
        dsn = index_dsn(declaration.target.dsn_env, index=index, environ=environment(workspace))
        embedder = bootstrap.build_embedding_provider(declaration.embedding_model)
        searched = bootstrap.build_index_search(dsn)
    except (ConfigError, ReadersRefused, UnknownProvider, IndexSearchFailed) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    # Each question of the gold set is a query like any other (R21.19).
    queries = [
        replace(each, query=_masked_query(declaration.pipeline, pipeline, path, each.query))
        for each in queries
    ]

    # Before any work: a run in the search experiment, named as a measurement
    # (R10.5, R11.37).
    tracker, experiment = bootstrap.tracking_for(
        workspace, declaration.pipeline, kind="search", name_kind="relevance"
    )
    try:
        report = measure_search(
            declaration=declaration,
            queries=queries,
            readers_of=lambda query: readers[query.name] or (),
            embedder=embedder,
            vectors=ArtifactCache(workspace, namespace="embed"),
            index=searched,
            held=_held(workspace, pipeline.sources),
            candidates=candidates,
            words=words,
        )
    except SearchRefused as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    except (ModelRequestFailed, IndexSearchFailed) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    if as_json:
        typer.echo(json.dumps(report.document(), ensure_ascii=False, indent=2))
    else:
        for line in measured_lines(report):
            typer.echo(line)
    if tracker is not None:
        directory = gold if gold.is_absolute() else workspace / gold
        record_relevance(
            tracker,
            experiment=experiment or "",
            declaration=declaration,
            report=report,
            gold=gold_hash(directory),
            started=started,
            environ=environment(workspace),
            dossier_version=version("dossier"),
            label=label,
        )
        typer.echo(f"recorded to MLflow: {experiment}", err=True)


def measured_lines(report: RelevanceReport) -> list[str]:
    """What a measurement prints: the means over the queries scored, then each query (R22.7).

    A query nothing answers is named and left out of the means (R22.4). Names
    are padded to the longest, so the measures read down in columns.
    """
    count = len(report.queries)
    head = f"{report.index} · {count} {'query' if count == 1 else 'queries'}"
    # A variant is named where the numbers are (R22.9, R22.10).
    head += "".join(f" · {each}" for each in report.variant)
    found = report.means
    if found.ndcg is None or found.recall is None:
        lines = [f"{head} · no query has a document judged relevant"]
    else:
        lines = [f"{head} · nDCG@10 {found.ndcg:.3f} · recall@10 {found.recall:.3f}"]
    width = max((len(each.query.name) for each in report.queries), default=0)
    for each in report.queries:
        score = each.measured
        name = each.query.name.ljust(width)
        if score.ndcg is None or score.recall is None:
            lines.append(f"  {name}  no relevant document judged")
        else:
            lines.append(
                f"  {name}  nDCG@10 {score.ndcg:.3f}  recall@10 {score.recall:.3f}  "
                f"{score.unjudged} unjudged"
            )
    return lines


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
    index does not reflect (R19.7, R19.10, R19.12)."""
    lines = [
        header(
            report.index, found=len(report.found), readers=report.readers, chunks=report.chunks
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
    """The same results as JSON, for a script or an agent (R19.12 row 2)."""
    return {
        "index": report.index,
        "query": report.query,
        "readers": None if report.readers is None else list(report.readers),
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


def _refuse_masked_where(
    pipeline: str, config: PipelineConfig, path: Path, given: list[str], *, index: str
) -> None:
    """Stop a search of a masked index on a `--where` value its masker detects (R21.26)."""
    values = where_values(given)
    if not values:
        return
    masking, masker = bootstrap.masking_for(pipeline, config, path)
    if masking is None or masker is None:
        return
    try:
        detected = detected_in(values, masking=masking, masker=masker)
    except MaskerUnavailable as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error
    if detected:
        typer.echo(masked_where_refusal(index, detected), err=True)
        raise typer.Exit(code=2)


def _masked_query(pipeline: str, config: PipelineConfig, path: Path, query: str) -> str:
    """`query` as the index's pipeline masks it, or as typed when it masks nothing (R21.19)."""
    masking, masker = bootstrap.masking_for(pipeline, config, path)
    if masking is None or masker is None:
        return query
    try:
        return mask_query(query, masking=masking, masker=masker)
    except MaskerUnavailable as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error
