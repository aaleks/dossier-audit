"""R11.34 — a `dossier search` is one MLflow trace in its pipeline's `search`
experiment, with an EMBEDDING and a RETRIEVER span, and no run.

A search changes nothing, so it opens no run. Its trace is what MLflow's
retrieval views read, and what a later retrieval eval would score.

Over R19.8's workspace, with tracking on and a fake tracker, as R11.33's are.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance import test_R019_8__search_lists_what_answers_the_query as searched
from tests.acceptance.test_R010_5__an_unreachable_server_refuses_before_any_work import URI
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import INDEX, PIPELINE
from tests.fakes import FakeTracker

QUERY = searched.QUERY

# R19.8's workspace, synced, run and embedded; its fixtures shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)


def _tracked(monkeypatch) -> FakeTracker:
    import dossier.cli.bootstrap as cli

    tracker = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    return tracker


def _search(workspace: Path, monkeypatch, *more: str):
    return _cli(workspace, monkeypatch, "search", INDEX, QUERY, *more)


class TestASearchIsOneTrace:
    """R11.34 — one trace, two spans, no run."""

    def test_a_search_is_one_trace_and_no_run(self, embedded: Path, monkeypatch):
        """Row 1 — the one searched with tracking on."""
        tracker = _tracked(monkeypatch)

        result = _search(embedded, monkeypatch, "--where", "component=checkout")

        assert result.exit_code == 0, result.output
        assert tracker.runs == []
        (trace,) = tracker.traces
        assert tracker.trace_experiments == [f"dossier-audit/{PIPELINE}/search"]
        assert trace.inputs == {
            "query": QUERY,
            "where": {"component": ["checkout"]},
            "reader": None,
        }
        assert trace.outputs == [f"{searched.carried.SOURCE_ID}:INC-4830"]
        embedding, retriever = trace.spans
        assert embedding["kind"] == "embedding"
        assert embedding["dossier.model"] == searched.carried.EMBEDDING_MODEL
        assert embedding["dossier.tokens"] > 0 and embedding["dossier.cached"] is False
        assert retriever["kind"] == "retriever"
        (first,) = retriever["dossier.results"]
        assert first["rank"] == 1
        assert first["document_id"].endswith(":INC-4830")
        assert first["score"] > 0
        assert tracker.traces_ended == 1

    def test_a_cached_query_is_marked_cached(self, embedded: Path, monkeypatch):
        """Row 2 — the one asked a second time."""
        assert _search(embedded, monkeypatch).exit_code == 0
        tracker = _tracked(monkeypatch)

        assert _search(embedded, monkeypatch).exit_code == 0

        (trace,) = tracker.traces
        embedding = trace.spans[0]
        assert (embedding["dossier.tokens"], embedding["dossier.cached"]) == (0, True)

    def test_a_refused_search_records_nothing(self, embedded: Path, monkeypatch):
        """Row 3, counter-example — the one on a field the index does not filter on."""
        tracker = _tracked(monkeypatch)

        result = _search(embedded, monkeypatch, "--where", "root_cause=certificate")

        assert result.exit_code == 2
        assert tracker.traces == [] and tracker.runs == []

    def test_tracking_off_records_nothing_and_searches_as_before(
        self, embedded: Path, monkeypatch
    ):
        """Row 4, counter-example — the one with tracking off."""
        import dossier.cli.bootstrap as cli

        tracker = FakeTracker()
        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)

        result = _search(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[1].startswith("1. INC-4830")
        assert tracker.traces == [] and tracker.runs == []
