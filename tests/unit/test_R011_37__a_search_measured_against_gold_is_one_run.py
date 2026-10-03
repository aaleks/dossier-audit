"""R11.37 — a search measured against relevance gold is one MLflow run of its
measures, in its pipeline's `search` experiment.

A search opens no run (R11.35); a measurement does, as an eval does, because
what it records is a score to compare across measurements. Over R19.12's
workspace, with tracking on and a fake tracker, as R11.35's are.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.acceptance import (
    test_R019_12__search_lists_what_answers_the_query_for_its_readers as searched,
)
from tests.acceptance.test_R022_7__search_gold_prints_each_querys_measures import (
    INC_4830,
    NAME,
    measure,
    write_gold,
)
from tests.unit.test_R011_35__a_search_is_one_trace import _tracked

# R19.12's workspace, its fixtures shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)


class TestASearchMeasuredAgainstGoldIsOneRun:
    """R11.37 — one run of the means, each query's search still one trace."""

    def test_the_measurement_is_one_run_of_its_means(self, embedded: Path, monkeypatch):
        """Row 1 — the one measured with tracking on."""
        write_gold(embedded, {INC_4830: 2})
        tracker = _tracked(monkeypatch)

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        (run,) = tracker.runs
        assert run.experiment == f"dossier-audit/{searched.carried.PIPELINE}/search"
        assert run.name.startswith("relevance incidents ")
        assert run.tags["dossier.kind"] == "relevance"
        assert run.metrics == {
            "ndcg_at_10": 1.0,
            "recall_at_10": 1.0,
            "queries": 1,
            "unscored": 0,
        }
        assert run.params["index"] == "incidents"
        assert run.params["embedding_model"] == searched.carried.EMBEDDING_MODEL
        assert len(run.params["gold_hash"]) == 64
        relevance = json.loads(run.artifacts["relevance.json"])
        assert [query["name"] for query in relevance["queries"]] == [NAME]
        assert run.status == "FINISHED"
        # Closed, and nothing lost: a query's trace recorded through a plain
        # search's `use_experiment` left the run unclosable, live on 2026-10-03.
        assert "could not be recorded" not in result.stderr

    def test_each_query_is_still_one_trace(self, embedded: Path, monkeypatch):
        """Row 2 — the one with two queries: two search traces."""
        write_gold(embedded, {INC_4830: 2})
        write_gold(embedded, {INC_4830: 1}, name="checkout-outage")
        tracker = _tracked(monkeypatch)

        assert measure(embedded, monkeypatch).exit_code == 0

        searches = [
            trace for trace in tracker.traces if trace.tags.get("dossier.kind") == "search"
        ]
        assert [trace.inputs["query"] for trace in searches] == [searched.QUERY] * 2

    def test_with_tracking_off_nothing_is_recorded(self, embedded: Path, monkeypatch):
        """Row 3, counter-example — the one with tracking off: the same lines, no record."""
        write_gold(embedded, {INC_4830: 2})

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        assert "recorded to MLflow" not in result.output
