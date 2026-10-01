"""R19.8 — `dossier search INDEX QUERY` prints the documents that answer it,
best first.

The outer loop of spec 019. A person syncs, runs the pipeline that extracts
the taxonomy, embeds, and asks the index a question in plain words: the
documents that answer it are listed, each at its best chunk, with the values
the run grounded. The embedding model and the index are fakes, as in R18.7 and
R18.11; the fake index ranks by meaning and by words over what `embed` wrote.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance import test_R018_11__embed_carries_the_runs_record as carried
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import INDEX

QUERY = "certificate expired at checkout"

# R18.11's workspace, its fixtures shared rather than copied.
issues, embedder, index, run_once = (
    carried.issues,
    carried.embedder,
    carried.index,
    carried.run_once,
)


@pytest.fixture
def embedded(run_once: Path, monkeypatch, index) -> Path:
    """R18.11's workspace, synced, run and embedded, and searched through its index."""
    import dossier.cli.bootstrap as cli

    result = _cli(run_once, monkeypatch, "embed", INDEX)
    assert result.exit_code == 0, result.output
    monkeypatch.setattr(cli, "build_index_search", lambda dsn: index, raising=False)
    return run_once


class TestSearchListsWhatAnswersTheQuery:
    """R19.8 — the documents that answer a query, best first."""

    def test_the_document_that_answers_is_listed_with_its_values(
        self, embedded: Path, monkeypatch
    ):
        """Row 1 — the one synced, run, embedded and searched."""
        result = _cli(embedded, monkeypatch, "search", INDEX, QUERY)

        assert result.exit_code == 0, result.output
        lines = result.stdout.splitlines()
        assert lines[0] == f"{INDEX} · 1 document · not filtered by reader", lines
        assert lines[1].startswith("1. INC-4830"), lines
        # A result's details are indented under it.
        details = [line.strip() for line in lines[2:]]
        assert "component: checkout · failure_category: certificate-expiry" in details, lines
        excerpt = lines[3]
        assert len(excerpt.strip()) <= 201 and "\n" not in excerpt, excerpt

    def test_json_prints_the_same_results(self, embedded: Path, monkeypatch):
        """Row 2 — the one asked for JSON, for a script."""
        result = _cli(embedded, monkeypatch, "search", INDEX, QUERY, "--json")

        assert result.exit_code == 0, result.output
        printed = json.loads(result.stdout)
        assert {"index", "query", "reader", "results"} <= set(printed), printed
        assert (printed["index"], printed["query"], printed["reader"]) == (INDEX, QUERY, None)
        (first,) = printed["results"]
        assert first["rank"] == 1
        assert first["document_id"].endswith(":INC-4830"), first
        assert first["values"] == {
            "component": "checkout",
            "failure_category": "certificate-expiry",
        }
        assert {"title", "heading_path", "kind", "text", "score"} <= set(first), first

    def test_a_query_no_word_matches_is_still_found_by_meaning(
        self, embedded: Path, monkeypatch
    ):
        """Row 3, counter-example — the one only meaning can answer."""
        result = _cli(embedded, monkeypatch, "search", INDEX, "kubernetes")

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[1].startswith("1. INC-4830"), result.output

    def test_a_filter_nothing_carries_finds_nothing(self, embedded: Path, monkeypatch):
        """Row 4, counter-example — the one filtered on a value no document carries."""
        result = _cli(
            embedded, monkeypatch, "search", INDEX, QUERY, "--where", "component=payments-api"
        )

        assert result.exit_code == 0, result.output
        assert "no documents found" in result.stdout.splitlines(), result.output
