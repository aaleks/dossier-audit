"""R21.18 — an index's masking never changes under it: `embed` refuses to write it
masked over rows written unmasked, and the other way round.

Postgres keeps a rewritten row in its write-ahead log, in its dead tuples until
a vacuum, and in every backup taken. Rewriting an index's rows masked does not
take the names out of it, so `embed` refuses rather than pretend it did. A new
index, or one emptied first, is the remedy. How an index was last written is
recorded on this machine, in `.dossier/index/<index>.json`, because the index
port reads back nothing but ids and content hashes (R0.19).

The embedding model, the index and the masker are fakes; the index can be
emptied by hand, as a person could empty its tables.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import (
    DECLARATION,
    DSN_ENV,
    _cli,
)
from tests.fakes import FakeEmbeddingProvider, FakeIndexSink, FakeMasker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

INDEX = "incidents"
NOTE = (
    "# PLAY-6001\n\n## Report\n\nErika Mustermann holds account CH93 0076 2011 6238 5295 7.\n"
)
MASKING = (
    "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON, IBAN_CODE]\n"
)


class Workspace:
    """`PLAY-6001` synced, its index declared, and switches for the pipeline's masking."""

    def __init__(self, workspace: Path, monkeypatch) -> None:
        import dossier.cli.bootstrap as cli

        self.root, self.monkeypatch = workspace, monkeypatch
        (workspace / "sources.yaml").write_text(
            f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n"
            "    acl: [incident-response]\n",
            encoding="utf-8",
        )
        self.pipeline = write_pipeline(workspace, sources=[SOURCE_ID])
        self.unmasked = self.pipeline.read_text(encoding="utf-8")
        masking = self.pipeline.parent / "masking"
        masking.mkdir()
        self.declaration = masking / "cid.yaml"
        self.declaration.write_text(MASKING, encoding="utf-8")
        (workspace / "indexes").mkdir()
        (workspace / "indexes" / f"{INDEX}.yaml").write_text(DECLARATION, encoding="utf-8")
        register_connector(
            monkeypatch,
            SOURCE_TYPE,
            lambda config, *, workspace: IssueTracker({"PLAY-6001": NOTE}),
        )
        self.sink, self.embedder = FakeIndexSink(), FakeEmbeddingProvider()
        monkeypatch.setattr(
            cli, "build_masker", lambda declaration: FakeMasker(), raising=False
        )
        monkeypatch.setattr(cli, "build_embedding_provider", lambda model_id: self.embedder)
        monkeypatch.setattr(cli, "build_index_sink", lambda dsn: self.sink)
        monkeypatch.setenv(DSN_ENV, "postgresql://dossier@127.0.0.1:5435/dossier")
        assert self.cli("sync", PIPELINE).exit_code == 0

    def cli(self, *args: str):
        return _cli(self.root, self.monkeypatch, *args)

    def mask(self, masked: bool) -> None:
        text = self.unmasked + ("masking: masking/cid.yaml\n" if masked else "")
        self.pipeline.write_text(text, encoding="utf-8")

    def embed(self):
        return self.cli("embed", INDEX)

    @property
    def record(self) -> Path:
        return self.root / ".dossier" / "index" / f"{INDEX}.json"


def _refused(result, workspace: Workspace, *, calls: int, writes: int) -> None:
    assert result.exit_code == 2, result.output
    assert INDEX in result.output
    assert "write-ahead log" in result.output
    assert "a new index, or empty this one" in result.output
    assert workspace.embedder.calls == calls, "nothing was embedded"
    assert workspace.sink.writes == writes, "nothing was written"


class TestAnIndexsMaskingNeverChangesUnderIt:
    """R21.18 — masked over unmasked, or unmasked over masked, is refused."""

    def test_an_index_written_unmasked_is_not_written_masked(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where `masking:` is declared after an unmasked embed."""
        w = Workspace(workspace, monkeypatch)
        w.mask(False)
        assert w.embed().exit_code == 0
        calls, writes = w.embedder.calls, w.sink.writes
        w.mask(True)

        _refused(w.embed(), w, calls=calls, writes=writes)

    def test_rows_no_record_describes_were_written_unmasked(self, workspace: Path, monkeypatch):
        """Row 2: the one where the index holds rows from before the record existed."""
        w = Workspace(workspace, monkeypatch)
        w.mask(False)
        assert w.embed().exit_code == 0
        w.record.unlink()
        calls, writes = w.embedder.calls, w.sink.writes
        w.mask(True)

        _refused(w.embed(), w, calls=calls, writes=writes)

    def test_an_index_written_masked_is_not_written_unmasked(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where `masking:` is removed: its readers rely on it staying masked."""
        w = Workspace(workspace, monkeypatch)
        w.mask(True)
        assert w.embed().exit_code == 0
        calls, writes = w.embedder.calls, w.sink.writes
        w.mask(False)

        _refused(w.embed(), w, calls=calls, writes=writes)

    def test_masked_over_masked_with_a_new_declaration_is_written(
        self, workspace: Path, monkeypatch
    ):
        """Row 4: the one where `allow.txt` is edited: a change of masking, not of whether."""
        w = Workspace(workspace, monkeypatch)
        w.mask(True)
        assert w.embed().exit_code == 0
        w.declaration.write_text(MASKING + "allow: masking/allow.txt\n", encoding="utf-8")
        (w.declaration.parent / "allow.txt").write_text("Oracle\n", encoding="utf-8")

        result = w.embed()

        assert result.exit_code == 0, result.output

    def test_an_empty_index_is_written_masked_and_the_record_says_so(
        self, workspace: Path, monkeypatch
    ):
        """Row 5, a counter-example: the one where the first embed is masked."""
        w = Workspace(workspace, monkeypatch)
        w.mask(True)

        result = w.embed()

        assert result.exit_code == 0, result.output
        assert json.loads(w.record.read_text(encoding="utf-8"))["masker"]["id"] == "fake"
        held = " ".join(repr(chunks) for chunks in w.sink.chunks.values())
        assert "[PERSON_1]" in held and "Erika" not in held
