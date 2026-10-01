"""R18.7 — `dossier embed INDEX` builds the index from what was synced.

The outer loop of spec 018's first slice. A person syncs a pipeline's sources,
declares an index over them, and embeds: every active document is in the index
with its chunks and their vectors. Embedding again with nothing changed asks
the model nothing and writes nothing, because the index is derived data and the
vectors are cached (R18.3, R18.4).

The embedding model and the index are fakes, reached through the two seams
`dossier.cli.bootstrap` builds them with, as a model client is. The fake model
counts its requests, and the fake index holds what was written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakeEmbeddingProvider, FakeIndexSink, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

INDEX = "incidents"
EMBEDDING_MODEL = (
    "ollama:qwen3-embedding:4b-fp16"
    "@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
)
DSN_ENV = "DOSSIER_INDEX_DSN"
DECLARATION = f"""\
pipeline: {PIPELINE}
embedding_model: {EMBEDDING_MODEL}
chunker: {{name: headings, max_chars: 2000}}
target: {{dsn_env: {DSN_ENV}}}
"""


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def index() -> FakeIndexSink:
    return FakeIndexSink()


@pytest.fixture
def synced(workspace: Path, monkeypatch, embedder, index) -> Path:
    """`incident-audit`'s four issues synced, and `indexes/incidents.yaml` over them."""
    return synced_workspace(workspace, monkeypatch, embedder=embedder, index=index)


def synced_workspace(
    workspace: Path, monkeypatch, *, embedder: FakeEmbeddingProvider, index: FakeIndexSink
) -> Path:
    """`synced`, as a function, for the unit tests of spec 018 to build on."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n"
        "    acl: [incident-response]\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    (workspace / "indexes").mkdir()
    (workspace / "indexes" / f"{INDEX}.yaml").write_text(DECLARATION, encoding="utf-8")
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output

    monkeypatch.setattr(
        cli, "build_embedding_provider", lambda model_id: embedder, raising=False
    )
    monkeypatch.setattr(cli, "build_index_sink", lambda dsn: index, raising=False)
    monkeypatch.setenv(DSN_ENV, "postgresql://dossier@127.0.0.1:5433/dossier")
    return workspace


class TestEmbedBuildsTheIndexFromWhatWasSynced:
    """R18.7 — every active document in the index, and nothing asked twice."""

    def test_the_first_embed_writes_every_active_document_with_its_vectors(
        self, synced: Path, monkeypatch, embedder, index
    ):
        """Row 1 — the one embedding four synced issues for the first time."""
        result = _cli(synced, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert f"{INDEX} · 4 chunks · 4 embedded · 0 cached · 4 written · 0 removed" in (
            result.output.splitlines()
        ), result.output
        assert [document.key for document in index.held_documents(INDEX)] == sorted(ISSUES)
        chunks = index.held_chunks(INDEX)
        assert len(chunks) == 4
        assert {len(chunk.embedding) for chunk in chunks} == {2560}
        assert embedder.calls >= 1

    def test_a_second_embed_with_nothing_changed_asks_nothing_and_writes_nothing(
        self, synced: Path, monkeypatch, embedder, index
    ):
        """Row 2 — the one embedded twice, with nothing synced between."""
        first = _cli(synced, monkeypatch, "embed", INDEX)
        assert first.exit_code == 0, first.output
        asked, written = embedder.calls, index.writes

        result = _cli(synced, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert f"{INDEX} · 4 chunks · 0 embedded · 4 cached · 0 written · 0 removed" in (
            result.output.splitlines()
        ), result.output
        assert embedder.calls == asked
        assert index.writes == written

    def test_an_unset_connection_variable_is_refused_before_any_model_is_asked(
        self, synced: Path, monkeypatch, embedder, index
    ):
        """Row 3, counter-example — the one with no `DOSSIER_INDEX_DSN` set."""
        monkeypatch.delenv(DSN_ENV)

        result = _cli(synced, monkeypatch, "embed", INDEX)

        assert result.exit_code == 2
        assert DSN_ENV in result.stderr
        assert embedder.calls == 0
        assert index.writes == 0
