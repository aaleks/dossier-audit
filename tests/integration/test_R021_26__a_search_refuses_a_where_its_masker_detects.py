"""R21.26 — a search over a masked index refuses a `--where` value its masker
detects, and sends it nowhere.

R21.19 masked a search's query and left its filters as typed, so a client
number typed into `--where` reached the index's query and the trace MLflow
records. Masking it would not help: each document numbers its own values
(R21.2), and `[CLIENT_NUMBER_1]` is a different client in each. So it is
refused, by field and type, before anything is asked.

The index is built masked first, as `dossier embed` builds it (R21.16), and
filters on `severity` and `affected_systems`; the embedding model, the index,
the masker and the tracker are fakes, as R21.19's are.
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
from tests.integration.test_R021_19__a_search_masks_its_query import (
    MASKING,
    NOTE,
    URI,
    Unavailable,
)
from tests.pipelines import write_pipeline
from tests.scoring_example import PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

INDEX = "incidents"
FILTERED = DECLARATION + "fields:\n  filter: [severity, affected_systems]\n"
CLIENT = "affected_systems=CIF 0042-118733"


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
    (workspace / "indexes" / f"{INDEX}.yaml").write_text(FILTERED, encoding="utf-8")
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
    embedded = _cli(workspace, monkeypatch, "embed", INDEX)
    assert embedded.exit_code == 0, embedded.output
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    return sink, embedder, tracker


def _search(workspace: Path, monkeypatch, where: str):
    return _cli(
        workspace,
        monkeypatch,
        "search",
        INDEX,
        "settlement held",
        "--as",
        "incident-response",
        "--where",
        where,
    )


def _recorded(tracker: FakeTracker) -> str:
    return repr(tracker.runs) + repr(tracker.runless_traces)


class TestASearchRefusesAWhereItsMaskerDetects:
    """R21.26 — a detected value is refused by field and type, and goes nowhere."""

    def test_a_client_number_in_a_filter_is_refused_by_field_and_type(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where a client number is typed into `--where`."""
        sink, embedder, tracker = _workspace(workspace, monkeypatch)
        asked, recorded = embedder.calls, _recorded(tracker)

        result = _search(workspace, monkeypatch, CLIENT)

        assert result.exit_code == 2, result.output
        assert "affected_systems" in result.stderr and "CLIENT_NUMBER" in result.stderr
        assert [value for value in CANARIES if value in result.output] == []
        assert embedder.calls == asked
        assert sink.searches == []
        assert _recorded(tracker) == recorded

    def test_a_filter_with_nothing_detected_is_searched_as_typed(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where the filter is a category."""
        sink, _, tracker = _workspace(workspace, monkeypatch)

        result = _search(workspace, monkeypatch, "severity=major")

        assert result.exit_code == 0, result.output
        assert sink.searches[-1]["where"] == {"severity": ("major",)}
        assert "'where': {'severity': ['major']}" in _recorded(tracker)

    def test_a_masker_that_cannot_run_sends_the_filter_nowhere(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where the pipeline's masker has a model missing."""
        import dossier.cli.bootstrap as cli

        sink, embedder, tracker = _workspace(workspace, monkeypatch)
        monkeypatch.setattr(cli, "build_masker", lambda declaration: Unavailable())
        asked, recorded = embedder.calls, _recorded(tracker)

        result = _search(workspace, monkeypatch, CLIENT)

        assert result.exit_code == 2, result.output
        assert "uv sync --extra masking --extra masking-models" in result.output
        assert embedder.calls == asked
        assert sink.searches == []
        assert _recorded(tracker) == recorded

    def test_an_unmasked_indexs_filter_is_searched_as_typed(self, workspace: Path, monkeypatch):
        """Row 4, a counter-example: the one where the pipeline declares no masking."""
        sink, _, _ = _workspace(workspace, monkeypatch, masked=False)

        result = _search(workspace, monkeypatch, CLIENT)

        assert result.exit_code == 0, result.output
        assert sink.searches[-1]["where"] == {"affected_systems": ("CIF 0042-118733",)}
