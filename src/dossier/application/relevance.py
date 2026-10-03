"""Measuring a search against relevance gold (spec 022).

Each query of the gold set is searched as its readers, ten documents deep, as
`dossier search` searches one, and the ids it lists are measured against what a
person judged, by `dossier.domain.relevance`. The search is the same search: a
measured query is embedded only on a cache miss (R19.3), and is one trace
(R11.35).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dossier.application.search import SearchReport, search_index, search_trace
from dossier.domain.gold import gold_set_hash
from dossier.domain.index import IndexDeclaration
from dossier.domain.ports import ArtifactStore, EmbeddingProvider, IndexSearch, Tracker
from dossier.domain.relevance import (
    CUT,
    Means,
    Measured,
    RelevanceQuery,
    any_words,
    means,
    measured,
    relevance_document,
    variant,
)
from dossier.domain.search import CANDIDATES
from dossier.domain.tracking import label_for, run_name
from dossier.domain.tracking import tags as tracking_tags


@dataclass(frozen=True)
class MeasuredQuery:
    """One query of the gold set: what it is, what the search listed, how that measured."""

    query: RelevanceQuery
    readers: tuple[str, ...]
    listed: tuple[str, ...]
    measured: Measured
    # The search it was, for its trace (R11.35).
    search: SearchReport


@dataclass(frozen=True)
class RelevanceReport:
    """A measurement: each query, in the gold set's order, and the means over them."""

    index: str
    queries: tuple[MeasuredQuery, ...]
    means: Means
    # The variant measured: each list's depth, and how its words match (R22.9, R22.10).
    candidates: int = CANDIDATES
    words: str = "all"

    @property
    def variant(self) -> tuple[str, ...]:
        return variant(self.candidates, self.words)

    def document(self) -> dict[str, object]:
        """What `--json` prints and `relevance.json` holds, in one shape (R22.7, R11.37)."""
        return relevance_document(
            self.index,
            [(each.query, each.readers, each.listed, each.measured) for each in self.queries],
            self.means,
        )


def measure_search(
    *,
    declaration: IndexDeclaration,
    queries: Sequence[RelevanceQuery],
    readers_of: Callable[[RelevanceQuery], tuple[str, ...]],
    embedder: EmbeddingProvider,
    vectors: ArtifactStore,
    index: IndexSearch,
    held: Mapping[str, str],
    candidates: int | None = None,
    words: str = "all",
) -> RelevanceReport:
    """Search each query as its readers, ten documents deep, and measure what it listed.

    Unfiltered, and documents rather than chunks: the measures are of what a
    reader sees first (R22.8). `readers_of` is the command's own check of a
    query's readers, as `--as` is checked (R19.10). `candidates` and `words`
    are the variant measured; by default, search as it is (R22.9, R22.10).
    """
    depth = CANDIDATES if candidates is None else candidates
    found: list[MeasuredQuery] = []
    for query in queries:
        readers = readers_of(query)
        report = search_index(
            declaration=declaration,
            query=query.query,
            where={},
            readers=readers,
            limit=CUT,
            chunks=False,
            embedder=embedder,
            vectors=vectors,
            index=index,
            held=held,
            candidates=depth,
            words=any_words(query.query) if words == "any" else None,
        )
        listed = tuple(each.document.document_id for each in report.found)
        found.append(
            MeasuredQuery(
                query=query,
                readers=readers,
                listed=listed,
                measured=measured(query.name, listed, query.judged),
                search=report,
            )
        )
    return RelevanceReport(
        index=declaration.name,
        queries=tuple(found),
        means=means([each.measured for each in found]),
        candidates=depth,
        words=words,
    )


def gold_hash(directory: Path) -> str:
    """The hash of a relevance gold set: each file's name and content (R11.37, R0.7)."""
    return gold_set_hash({path.name: path.read_bytes() for path in directory.glob("*.yaml")})


def record_relevance(
    tracker: Tracker,
    *,
    experiment: str,
    declaration: IndexDeclaration,
    report: RelevanceReport,
    gold: str,
    started: str,
    environ: Mapping[str, str],
    dossier_version: str,
    label: str = "",
) -> None:
    """Record a measurement as one MLflow run in the search experiment (R11.37).

    A search opens no run (R11.35). A measurement does, as an eval does: what it
    records is a score to compare with the next measurement's. Each query's
    search is still one trace, as any search's is.
    """
    label = label_for(label, environ)
    tracker.start_run(
        experiment=experiment,
        name=run_name(
            kind="relevance",
            values={"index": declaration.name, "started": started, "label": label},
            environ=environ,
        ),
        tags=tracking_tags(
            kind="relevance", pipeline=declaration.pipeline, label=label, environ=environ
        ),
    )
    params = {
        "index": declaration.name,
        "embedding_model": declaration.embedding_model,
        "gold_hash": gold,
        # The variant measured, so two measurements compare like with like.
        "candidates": str(report.candidates),
        "words": report.words,
    }
    if dossier_version:
        # Which dossier measured (R11.19).
        params["dossier_version"] = dossier_version
    tracker.log_params(params)
    metrics: dict[str, float] = {
        "queries": len(report.queries),
        "unscored": len(report.means.unscored),
    }
    if report.means.ndcg is not None and report.means.recall is not None:
        metrics["ndcg_at_10"] = report.means.ndcg
        metrics["recall_at_10"] = report.means.recall
    tracker.log_metrics(metrics)
    tracker.log_artifact(
        "relevance.json",
        (json.dumps(report.document(), ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    # Each query's search is one trace, under this run, where `end_run` looks
    # for it (R10.24). Not through `record_search`: its `use_experiment` would
    # send the traces to no run and leave this one unclosable.
    for each in report.queries:
        search_trace(
            tracker,
            report=each.search,
            where={},
            pipeline=declaration.pipeline,
            environ=environ,
            label=label,
        )
    tracker.end_run(status="FINISHED")
