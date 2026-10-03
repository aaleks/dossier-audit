"""R21.17 — a masked index carries a record only from a run whose manifest pins the
masker and declaration it masks with.

The record chunk is a run's free-text answers (R18.9). A run made before
masking was declared answered from the unmasked text, and one masked by an
earlier declaration may have let through a type declared since. Either way its
answers hold what the index's own masking would not, so a masked index carries
the record only of a run masked exactly as it masks. Its body chunks are
written regardless: they are cut from today's masked view (R21.16).

`INC-4830` names a client, `Erika Mustermann`, and states its root cause. The
model answering the run is scripted per document, and the embedding model, the
index and the masker are fakes.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import (
    DSN_ENV,
    _cli,
)
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import (
    DECLARATION,
    INDEX,
    PIPELINE,
    TAXONOMY,
)
from tests.fakes import FakeEmbeddingProvider, FakeIndexSink, FakeMasker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import SOURCE_ID, SOURCE_TYPE, IssueTracker, RoutedModel, found

ROOT_CAUSE = (
    "Certificate renewal and certificate deployment were two separate processes, "
    "and only the first was automated."
)
NOTE = (
    "# INC-4830\n\n"
    "Erika Mustermann reported that checkout returned 502 after the TLS "
    "certificate expired.\n\n"
    "## Root cause\n\n"
    f"{ROOT_CAUSE}\n"
)
ANSWERS = {
    "INC-4830": [
        found(
            "INC-4830", "failure_category", "certificate-expiry", "the TLS certificate expired"
        ),
        found("INC-4830", "root_cause", ROOT_CAUSE, ROOT_CAUSE),
    ]
}
MASKING = "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON]\n"


def _workspace(workspace: Path, monkeypatch) -> tuple[Path, FakeIndexSink]:
    """`INC-4830` synced, its taxonomy and its index declared, and nothing masked yet."""
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
    (path.parent / "masking").mkdir()
    (path.parent / "masking" / "cid.yaml").write_text(MASKING, encoding="utf-8")
    (workspace / "indexes").mkdir()
    (workspace / "indexes" / f"{INDEX}.yaml").write_text(DECLARATION, encoding="utf-8")
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker({"INC-4830": NOTE})
    )
    sink = FakeIndexSink()
    embedder = FakeEmbeddingProvider()
    masker = FakeMasker()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    monkeypatch.setattr(cli, "build_masker", lambda declaration: masker, raising=False)
    monkeypatch.setattr(cli, "build_embedding_provider", lambda model_id: embedder)
    monkeypatch.setattr(cli, "build_index_sink", lambda dsn: sink)
    monkeypatch.setenv(DSN_ENV, "postgresql://dossier@127.0.0.1:5435/dossier")
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return path, sink


def _masked(path: Path) -> None:
    with path.open("a", encoding="utf-8") as pipeline:
        pipeline.write("masking: masking/cid.yaml\n")


def _ran(workspace: Path, monkeypatch) -> str:
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return sorted(path.name for path in (workspace / "runs").iterdir())[-1]


def _records(sink: FakeIndexSink) -> list:
    return [chunk for chunk in sink.held_chunks(INDEX) if chunk.kind == "record"]


def _body(sink: FakeIndexSink) -> str:
    return " ".join(chunk.text for chunk in sink.held_chunks(INDEX) if chunk.kind == "body")


class TestAMaskedIndexCarriesOnlyAMaskedRecord:
    """R21.17 — the record of a run masked exactly as the index masks, or none."""

    def test_a_run_masked_as_the_index_masks_is_carried(self, workspace: Path, monkeypatch):
        """Row 1: the one where the latest run was masked with today's declaration."""
        path, sink = _workspace(workspace, monkeypatch)
        _masked(path)
        _ran(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        (record,) = _records(sink)
        assert ROOT_CAUSE in record.text

    def test_a_run_made_before_masking_was_declared_is_not_carried(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where the latest run read the unmasked text."""
        path, sink = _workspace(workspace, monkeypatch)
        run = _ran(workspace, monkeypatch)
        _masked(path)

        result = _cli(workspace, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert _records(sink) == []
        assert f"no record: {run} did not mask as this index does" in result.output
        assert "[PERSON_1] reported" in _body(sink), "the body is still written, masked"

    def test_a_run_masked_by_another_declaration_is_not_carried(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where `ORGANIZATION` was declared after the run.

        The run's masking let organisations through, and its answers may name
        one that the index's masking would not.
        """
        path, sink = _workspace(workspace, monkeypatch)
        _masked(path)
        run = _ran(workspace, monkeypatch)
        declaration = path.parent / "masking" / "cid.yaml"
        declaration.write_text(
            MASKING.replace("[PERSON]", "[PERSON, IBAN_CODE]"), encoding="utf-8"
        )

        result = _cli(workspace, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert _records(sink) == []
        assert f"no record: {run} did not mask as this index does" in result.output

    def test_an_unmasked_pipelines_index_carries_its_latest_run(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, a counter-example: the one where nothing is declared, as R18.8 says."""
        _, sink = _workspace(workspace, monkeypatch)
        _ran(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        (record,) = _records(sink)
        assert ROOT_CAUSE in record.text
