"""R22.9 — `--candidates N` asks each of a measured search's two lists for N
chunks rather than 100.

Spec 019's question 1, answered by measuring the same gold at two depths. Only
a measurement takes it: search itself keeps 100 until the numbers decide. Over
R19.12's workspace, whose fake index records the depth each search asked for.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance import (
    test_R019_12__search_lists_what_answers_the_query_for_its_readers as searched,
)
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R022_7__search_gold_prints_each_querys_measures import (
    INC_4830,
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


class TestCandidatesSetsHowDeepAMeasurementSearches:
    """R22.9 — the depth a measurement asks, said where it is printed and recorded."""

    def test_each_list_is_asked_for_n_chunks(self, embedded: Path, monkeypatch, index):
        """Row 1 — the one measured 1000 deep."""
        write_gold(embedded, {INC_4830: 2})
        before = len(index.searches)

        result = measure(embedded, monkeypatch, "--candidates", "1000")

        assert result.exit_code == 0, result.output
        assert [asked["candidates"] for asked in index.searches[before:]] == [1000]
        assert result.stdout.splitlines()[0] == (
            "incidents · 1 query · candidates 1000 · nDCG@10 1.000 · recall@10 1.000"
        )

    def test_the_depth_is_a_param_of_the_run(self, embedded: Path, monkeypatch):
        """Row 2 — the same, with tracking on."""
        write_gold(embedded, {INC_4830: 2})
        tracker = _tracked(monkeypatch)

        assert measure(embedded, monkeypatch, "--candidates", "1000").exit_code == 0

        (run,) = tracker.runs
        assert run.params["candidates"] == "1000"

    def test_without_it_a_measurement_asks_as_every_search_does(
        self, embedded: Path, monkeypatch, index
    ):
        """Row 3, counter-example — the one measured as search asks, 100 deep."""
        write_gold(embedded, {INC_4830: 2})
        before = len(index.searches)
        tracker = _tracked(monkeypatch)

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        assert [asked["candidates"] for asked in index.searches[before:]] == [100]
        assert "candidates" not in result.stdout.splitlines()[0]
        (run,) = tracker.runs
        assert run.params["candidates"] == "100"

    def test_a_search_is_refused_a_depth(self, workspace: Path, monkeypatch):
        """Row 4 — the one asking a plain search for 1000."""
        result = _cli(
            workspace,
            monkeypatch,
            "search",
            searched.INDEX,
            searched.QUERY,
            "--candidates",
            "1000",
        )

        assert result.exit_code == 2, result.output
        assert result.stderr.splitlines() == [
            "--candidates needs --gold: it measures a variant, and search keeps 100"
        ]
