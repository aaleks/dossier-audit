"""R21.19 — a search over a masked index masks its query before it is embedded,
searched, printed or recorded.

A name typed into a query would otherwise reach the embedding model, the
vector cache's key, the words searched and the trace MLflow records -- the
places a masked index exists to keep it out of. Masked by the masker the
pipeline declares, the query also matches the placeholders the index holds.

The index is built masked first, as `dossier embed` builds it (R21.16); the
embedding model, the index, the masker and the tracker are fakes.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import (
    DECLARATION,
    DSN_ENV,
    _cli,
)
from tests.fakes import (
    CANARIES,
    FakeEmbeddingProvider,
    FakeIndexSink,
    FakeMasker,
    FakeTracker,
    register_connector,
)
from tests.pipelines import write_pipeline
from tests.scoring_example import PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

INDEX = "incidents"
URI = "http://localhost:5000"
NOTE = (
    "# PLAY-6001\n\n## Report\n\nErika Mustermann quoted her client number CIF 0042-118733.\n"
)
MASKING = (
    "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\n"
    "entities: [PERSON, CLIENT_NUMBER]\n"
)
QUERY = "Erika Mustermann complained about CIF 0042-118733"
MASKED = "[PERSON_1] complained about [CLIENT_NUMBER_1]"


class Unavailable(FakeMasker):
    """A masker whose model is missing on this machine."""

    def detect(self, text: str, *, language: str) -> list:
        from dossier.domain.masking import MaskerUnavailable

        raise MaskerUnavailable(
            "spaCy model en_core_web_lg 3.8.0 is not installed. Install it: "
            "uv sync --extra masking --extra masking-models"
        )


def _workspace(workspace: Path, monkeypatch, *, masked: bool = True):
    """`PLAY-6001` synced and embedded, masked or not; and the fakes it was built with."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n"
        "    acl: [incident-response]\n",
        encoding="utf-8",
    )
    path = write_pipeline(workspace, sources=[SOURCE_ID])
    if masked:
        with path.open("a", encoding="utf-8") as pipeline:
            pipeline.write("masking: masking/cid.yaml\n")
        (path.parent / "masking").mkdir()
        (path.parent / "masking" / "cid.yaml").write_text(MASKING, encoding="utf-8")
    (workspace / "indexes").mkdir()
    (workspace / "indexes" / f"{INDEX}.yaml").write_text(DECLARATION, encoding="utf-8")
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker({"PLAY-6001": NOTE})
    )
    sink, embedder, tracker = FakeIndexSink(), FakeEmbeddingProvider(), FakeTracker()
    monkeypatch.setattr(cli, "build_masker", lambda declaration: FakeMasker(), raising=False)
    monkeypatch.setattr(cli, "build_embedding_provider", lambda model_id: embedder)
    monkeypatch.setattr(cli, "build_index_sink", lambda dsn: sink)
    monkeypatch.setattr(cli, "build_index_search", lambda dsn: sink)
    monkeypatch.setenv(DSN_ENV, "postgresql://dossier@127.0.0.1:5435/dossier")
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    assert _cli(workspace, monkeypatch, "embed", INDEX).exit_code == 0
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    return sink, embedder, tracker


def _search(workspace: Path, monkeypatch, query: str):
    return _cli(workspace, monkeypatch, "search", INDEX, query, "--as", "incident-response")


class TestASearchMasksItsQuery:
    """R21.19 — the masked query, everywhere a query goes."""

    def test_the_query_is_masked_before_it_goes_anywhere(self, workspace: Path, monkeypatch):
        """Row 1: the one where a client's name and number are typed into the query."""
        sink, embedder, tracker = _workspace(workspace, monkeypatch)

        result = _search(workspace, monkeypatch, QUERY)

        assert result.exit_code == 0, result.output
        assert any(MASKED in text for text in embedder.requests[-1])
        assert sink.searches[-1]["words"] == MASKED
        recorded = repr(tracker.runs) + repr(tracker.runless_traces)
        assert MASKED in recorded
        leaked = result.output + recorded + " ".join(embedder.texts)
        assert [value for value in CANARIES if value in leaked] == []

    def test_a_query_with_nothing_detected_is_searched_as_typed(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where the query names no client."""
        sink, _, _ = _workspace(workspace, monkeypatch)

        result = _search(workspace, monkeypatch, "settlement export never ran")

        assert result.exit_code == 0, result.output
        assert sink.searches[-1]["words"] == "settlement export never ran"

    def test_a_masker_that_cannot_run_sends_the_query_nowhere(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where the pipeline's masker has a model missing."""
        import dossier.cli.bootstrap as cli

        sink, embedder, _ = _workspace(workspace, monkeypatch)
        monkeypatch.setattr(cli, "build_masker", lambda declaration: Unavailable())
        asked = embedder.calls

        result = _search(workspace, monkeypatch, QUERY)

        assert result.exit_code == 2, result.output
        assert "uv sync --extra masking --extra masking-models" in result.output
        assert embedder.calls == asked
        assert sink.searches == []

    def test_an_unmasked_indexs_query_is_searched_as_typed(self, workspace: Path, monkeypatch):
        """Row 4, a counter-example: the one where the pipeline declares no masking."""
        sink, _, _ = _workspace(workspace, monkeypatch, masked=False)

        result = _search(workspace, monkeypatch, QUERY)

        assert result.exit_code == 0, result.output
        assert sink.searches[-1]["words"] == QUERY
