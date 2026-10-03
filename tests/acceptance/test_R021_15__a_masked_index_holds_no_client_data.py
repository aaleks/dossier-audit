"""R21.15 — a masked pipeline's index holds no value its masker detects, and its
embedding model is asked about none.

The acceptance rule of spec 021's third part, and the second half of what
masking was asked for: a run must not push client data to a model, and an
embed must not push it to pgvector. A person syncs, runs the masked pipeline,
and embeds; every row the index is handed, every text the embedding model is
asked for, and every span the embed records holds placeholders where the
converted text held the client's name.

`INC-4830` names two people and states its root cause, which names one of them,
so the record chunk carried from the run is a masked answer too. The model is
scripted per document and answers with the masked text it was shown. The
embedding model, the index, the masker and the tracker are fakes.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import (
    DSN_ENV,
    EMBEDDING_MODEL,
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
from tests.scoring_example import SOURCE_ID, SOURCE_TYPE, IssueTracker, RoutedModel, found

PIPELINE = "incident-audit"
INDEX = "incidents"
URI = "http://localhost:5000"
CAUSE = "Hans Muster disabled the nightly settlement job by mistake."
NOTE = (
    "# INC-4830\n\n"
    "Erika Mustermann reported that her settlement to CH93 0076 2011 6238 5295 7 "
    "did not arrive.\n\n"
    "## Root cause\n\n"
    f"{CAUSE}\n"
)
MASKED_CAUSE = "[PERSON_2] disabled the nightly settlement job by mistake."
TAXONOMY = """\
fields:
  failure_category: {kind: enum, values: [settlement-delay, capacity-exhaustion]}
  root_cause:       {kind: free_text, judge: rubrics/root_cause.md}
"""
ANSWERS = {
    "INC-4830": [
        found("INC-4830", "failure_category", "settlement-delay", "did not arrive"),
        found("INC-4830", "root_cause", MASKED_CAUSE, MASKED_CAUSE),
    ]
}
DECLARATION = f"""\
pipeline: {PIPELINE}
embedding_model: {EMBEDDING_MODEL}
chunker: {{name: headings, max_chars: 2000}}
fields:
  filter: [failure_category]
  embed: [root_cause]
target: {{dsn_env: {DSN_ENV}}}
"""
MASKING = (
    "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON, IBAN_CODE]\n"
)


def _embedded(workspace: Path, monkeypatch, *, masked: bool = True):
    """`INC-4830` synced, run and embedded, recorded under `capture: full`; the fakes."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n"
        "    acl: [incident-response]\n",
        encoding="utf-8",
    )
    path = write_pipeline(
        workspace, sources=[SOURCE_ID], outputs={"extract": "schemas/taxonomy.yaml"}
    )
    (path.parent / "schemas" / "taxonomy.yaml").write_text(TAXONOMY, encoding="utf-8")
    if masked:
        with path.open("a", encoding="utf-8") as pipeline:
            pipeline.write("masking: masking/cid.yaml\n")
        (path.parent / "masking").mkdir()
        (path.parent / "masking" / "cid.yaml").write_text(MASKING, encoding="utf-8")
    (workspace / "indexes").mkdir()
    (workspace / "indexes" / f"{INDEX}.yaml").write_text(DECLARATION, encoding="utf-8")
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker({"INC-4830": NOTE})
    )
    sink, embedder, tracker, masker = (
        FakeIndexSink(),
        FakeEmbeddingProvider(),
        FakeTracker(),
        FakeMasker(),
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    monkeypatch.setattr(cli, "build_masker", lambda declaration: masker, raising=False)
    monkeypatch.setattr(cli, "build_embedding_provider", lambda model_id: embedder)
    monkeypatch.setattr(cli, "build_index_sink", lambda dsn: sink)
    monkeypatch.setenv(DSN_ENV, "postgresql://dossier@127.0.0.1:5435/dossier")
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    result = _cli(workspace, monkeypatch, "embed", INDEX)
    assert result.exit_code == 0, result.output
    return sink, embedder, tracker, masker


def _rows(sink: FakeIndexSink) -> str:
    """Every row the index was handed -- documents and chunks -- as one string."""
    return repr(list(sink.documents.values())) + repr(list(sink.chunks.values()))


def _held(text: str) -> list[str]:
    return [value for value in CANARIES if value in text]


class TestAMaskedIndexHoldsNoClientData:
    """R21.15 — the index, the embedding model and the embed's record: placeholders only."""

    def test_no_row_and_no_embedded_text_holds_a_canary(self, workspace: Path, monkeypatch):
        """Row 1: the one where the client's name never reaches the index."""
        sink, embedder, _, _ = _embedded(workspace, monkeypatch)

        rows = _rows(sink)

        assert _held(rows) == []
        assert _held(" ".join(embedder.texts)) == []
        assert "[PERSON_1] reported" in rows
        assert "[IBAN_CODE_1]" in rows

    def test_the_record_chunk_is_the_runs_masked_answer(self, workspace: Path, monkeypatch):
        """Row 2: the one where the root cause names a person, and the record is masked."""
        sink, _, _, _ = _embedded(workspace, monkeypatch)

        (record,) = [chunk for chunk in sink.held_chunks(INDEX) if chunk.kind == "record"]

        assert MASKED_CAUSE in record.text
        assert _held(record.text) == []

    def test_no_span_the_embed_records_holds_a_canary(self, workspace: Path, monkeypatch):
        """Row 3: the one where the embed is recorded under `capture: full`."""
        _, _, tracker, _ = _embedded(workspace, monkeypatch)

        recorded = repr(tracker.runs) + repr(tracker.runless_traces)

        assert tracker.runs, "the embed recorded nothing, so the rule is vacuous"
        assert _held(recorded) == []

    def test_an_unmasked_pipelines_index_holds_the_converted_text(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, a counter-example: the one where nothing is declared.

        The rows hold the converted text, as spec 018 writes them, and no
        masker is ever asked.
        """
        sink, _, _, masker = _embedded(workspace, monkeypatch, masked=False)

        assert "Erika Mustermann reported" in _rows(sink)
        assert masker.call_count == 0
