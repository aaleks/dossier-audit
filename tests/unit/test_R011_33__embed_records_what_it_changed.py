"""R11.33 — a `dossier embed` that changed the index is one MLflow run in its
pipeline's `embed` experiment, with a trace for each request for vectors.

As every command that changes something records it (R11.28). The run is opened
once the index is written, so what it records are the counts the line printed.
Each request for vectors is a model call, and a model call is what spec 011
traces. An `embed` that changed nothing records nothing.

Through the CLI, tracking on and a `FakeTracker`, over R18.7's workspace.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.acceptance.test_R010_5__an_unreachable_server_refuses_before_any_work import URI
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import (
    EMBEDDING_MODEL,
    INDEX,
    _cli,
    synced_workspace,
)
from tests.fakes import FakeEmbeddingProvider, FakeIndexSink, FakeTracker

EXPERIMENT = "dossier-audit/incident-audit/embed"


@pytest.fixture
def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def synced(workspace: Path, monkeypatch, embedder) -> Path:
    return synced_workspace(workspace, monkeypatch, embedder=embedder, index=FakeIndexSink())


def _tracked(monkeypatch) -> FakeTracker:
    import dossier.cli.bootstrap as cli

    tracker = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    return tracker


class TestEmbedRecordsWhatItChanged:
    """R11.33 — a run for an embed that wrote, a trace per request, none otherwise."""

    def test_an_embed_that_wrote_is_one_run_of_its_counts(self, synced: Path, monkeypatch):
        """Row 1 — the one embedding four synced issues, tracking on."""
        tracker = _tracked(monkeypatch)

        result = _cli(synced, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        (run,) = tracker.runs
        assert run.experiment == EXPERIMENT
        assert re.fullmatch(rf"embed {INDEX} \d{{8}}T\d{{6}}Z", run.name), run.name
        assert run.tags["dossier.kind"] == "embed"
        assert run.params["index"] == INDEX
        assert run.params["embedding_model"] == EMBEDDING_MODEL
        assert run.metrics == {
            "chunks": 4,
            "embedded": 4,
            "cached": 0,
            "written": 4,
            "removed": 0,
        }
        assert run.status == "FINISHED"

    def test_each_request_for_vectors_is_a_trace(self, synced: Path, monkeypatch, embedder):
        """Row 2 — the one whose four chunks are asked for in two requests."""
        import dossier.application.embed as embed

        tracker = _tracked(monkeypatch)
        monkeypatch.setattr(embed, "BATCH", 2)

        assert _cli(synced, monkeypatch, "embed", INDEX).exit_code == 0

        (run,) = tracker.runs
        assert embedder.calls == 2
        assert len(run.traces) == 2
        for trace, asked in zip(run.traces, embedder.requests, strict=True):
            (span,) = trace.spans
            assert span["kind"] == "embedding"
            assert span["name"] == EMBEDDING_MODEL
            assert len(span["dossier.chunks"]) == len(asked) == 2
            assert span["dossier.tokens"] == sum(len(text.split()) for text in asked)

    def test_the_record_is_said_where_it_was_made(self, synced: Path, monkeypatch):
        """Row 3 — the one whose last line says where it was recorded (R10.4 row 3)."""
        _tracked(monkeypatch)

        result = _cli(synced, monkeypatch, "embed", INDEX)

        assert result.output.splitlines()[-1] == f"recorded to MLflow: {EXPERIMENT}"

    def test_an_embed_that_changed_nothing_records_nothing(self, synced: Path, monkeypatch):
        """Row 4, counter-example — the one embedded a second time, nothing changed."""
        tracker = _tracked(monkeypatch)
        assert _cli(synced, monkeypatch, "embed", INDEX).exit_code == 0

        result = _cli(synced, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1
        assert "recorded to MLflow" not in result.output

    def test_with_tracking_off_nothing_is_recorded(self, synced: Path, monkeypatch):
        """Row 5, counter-example — the one with tracking off: no run, no server asked."""
        import dossier.cli.bootstrap as cli

        asked: list[object] = []
        monkeypatch.setattr(cli, "build_tracker", lambda settings: asked.append(settings))

        result = _cli(synced, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert asked == []
        assert "recorded to MLflow" not in result.output
