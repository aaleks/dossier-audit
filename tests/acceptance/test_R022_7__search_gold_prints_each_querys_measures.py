"""R22.7 — `dossier search INDEX --gold DIR` prints each query's nDCG@10,
recall@10 and unjudged count, then the means.

Over R19.12's workspace: `INC-4830` synced, run, embedded and searched through
a fake index that ranks what `embed` wrote. Its one document is the only one a
search can list, so where it lands is decided by what the gold judges.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.acceptance import (
    test_R019_12__search_lists_what_answers_the_query_for_its_readers as searched,
)
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli

GOLD = "gold/incidents-search"
NAME = "certificate-expired-at-checkout"
INC_4830 = f"{searched.carried.SOURCE_ID}:INC-4830"
INC_4821 = f"{searched.carried.SOURCE_ID}:INC-4821"

# R19.12's workspace, its fixtures shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)


def write_gold(
    workspace: Path,
    judged: dict[str, int],
    *,
    readers: tuple[str, ...] = (searched.READER,),
    name: str = NAME,
) -> None:
    """One relevance gold file, as `a.aleks` judged `certificate expired at checkout`."""
    directory = workspace / GOLD
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        f"query: {searched.QUERY}",
        f"readers: [{', '.join(readers)}]",
        "judged_by: a.aleks",
        "judged:",
        *(f"  {document}: {grade}" for document, grade in judged.items()),
    ]
    (directory / f"{name}.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def measure(workspace: Path, monkeypatch, *more: str):
    return _cli(workspace, monkeypatch, "search", searched.INDEX, "--gold", GOLD, *more)


class TestSearchGoldPrintsEachQuerysMeasures:
    """R22.7 — each query's measures, then the means; exit 0 whatever they are."""

    def test_the_answer_listed_first(self, embedded: Path, monkeypatch):
        """Row 1 — the one whose index lists `INC-4830` first."""
        write_gold(embedded, {INC_4830: 2, INC_4821: 0})

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            "incidents · 1 query · nDCG@10 1.000 · recall@10 1.000",
            f"  {NAME}  nDCG@10 1.000  recall@10 1.000  0 unjudged",
        ]

    def test_the_same_as_json(self, embedded: Path, monkeypatch):
        """Row 2 — the one asked for JSON."""
        write_gold(embedded, {INC_4830: 2, INC_4821: 0})

        result = measure(embedded, monkeypatch, "--json")

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == {
            "index": "incidents",
            "ndcg_at_10": 1.0,
            "recall_at_10": 1.0,
            "scored": 1,
            "unscored": [],
            "queries": [
                {
                    "name": NAME,
                    "query": searched.QUERY,
                    "readers": [searched.READER],
                    "ndcg_at_10": 1.0,
                    "recall_at_10": 1.0,
                    "unjudged": 0,
                    "listed": [INC_4830],
                }
            ],
        }

    def test_nothing_relevant_listed_is_scored_and_still_exits_0(
        self, embedded: Path, monkeypatch
    ):
        """Row 3, counter-example — the one listing nothing the gold judged relevant."""
        write_gold(embedded, {INC_4821: 2})

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            "incidents · 1 query · nDCG@10 0.000 · recall@10 0.000",
            f"  {NAME}  nDCG@10 0.000  recall@10 0.000  1 unjudged",
        ]

    def test_a_query_nothing_answers_is_named_beneath_the_means(
        self, embedded: Path, monkeypatch
    ):
        """R22.4 through the command — the one whose second query judges nothing relevant."""
        write_gold(embedded, {INC_4830: 2})
        write_gold(embedded, {INC_4830: 0}, name="unanswerable")

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        # Names are padded to the longest, so the measures read in columns.
        assert result.stdout.splitlines() == [
            "incidents · 2 queries · nDCG@10 1.000 · recall@10 1.000",
            f"  {NAME}  nDCG@10 1.000  recall@10 1.000  0 unjudged",
            f"  {'unanswerable'.ljust(len(NAME))}  no relevant document judged",
        ]
