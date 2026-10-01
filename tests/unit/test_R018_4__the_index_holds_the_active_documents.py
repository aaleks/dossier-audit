"""R18.4 — the index holds exactly the active documents of its pipeline's sources,
and writes only what changed.

The index is derived data. What it is handed is what the ledger holds active
(R2.7), and each document is written only when the hash of everything written
for it moves. Emptied by hand, it is rebuilt from the cache, asking no model.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import (
    INDEX,
    _cli,
    synced_workspace,
)
from tests.fakes import FakeEmbeddingProvider, FakeIndexSink, register_connector
from tests.scoring_example import ISSUES as SYNCED_ISSUES
from tests.scoring_example import PIPELINE, SOURCE_TYPE, IssueTracker
from tests.unit.test_R018_3__a_chunk_is_embedded_only_on_a_cache_miss import (
    declaration,
)

from dossier.application.embed import ToIndex, embed_index
from dossier.domain.chunks import HeadingsChunker
from dossier.domain.hashing import content_hash
from dossier.domain.ports import RawItem
from dossier.infrastructure.cache import ArtifactCache

ISSUES = {
    "INC-4821": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822": "# INC-4822\n\nFinance confirmed a total exposure CHF 12'500.\n",
}
NOTES = {
    "audit-note.pdf": "Audit note\n\nThe checkout path was reviewed after the declines.\n",
    "handover-note.md": "# Handover\n\nThe on-call rota changes on Monday.\n",
}
READERS = {"incidents-jira": ("incident-response",), "incidents-manual": ("incident-response",)}


def held(changed: dict[str, str] | None = None) -> list[ToIndex]:
    """Every document as the ledger holds it, with `changed` texts in place."""
    texts = [("incidents-jira", key, text) for key, text in ISSUES.items()]
    texts += [("incidents-manual", key, text) for key, text in NOTES.items()]
    documents = []
    for source, key, text in texts:
        now = (changed or {}).get(key, text)
        documents.append(
            ToIndex(
                source_id=source,
                key=key,
                snapshot=content_hash(now.encode("utf-8")),
                text=now,
            )
        )
    return documents


def embed(workspace: Path, documents, embedder, sink):
    return embed_index(
        declaration=declaration(),
        documents=documents,
        readers=READERS,
        chunker=HeadingsChunker(max_chars=2000),
        embedder=embedder,
        vectors=ArtifactCache(workspace, namespace="embed"),
        sink=sink,
    )


class TestTheIndexHoldsTheActiveDocuments:
    """R18.4 — the active documents, each written only when it changed."""

    def test_a_second_embed_with_nothing_changed_writes_nothing(self, tmp_path: Path):
        """Row 1 — the one embedded twice over the same holdings."""
        embedder, sink = FakeEmbeddingProvider(), FakeIndexSink()
        embed(tmp_path, held(), embedder, sink)

        report = embed(tmp_path, held(), embedder, sink)

        assert (report.written, report.removed) == (0, 0)
        assert (
            report.line
            == "incidents · 4 chunks · 0 embedded · 4 cached · 0 written · 0 removed"
        )

    def test_a_changed_document_is_rewritten_and_no_other(self, tmp_path: Path):
        """Row 2 — the one where `INC-4822` was re-synced with new content."""
        embedder, sink = FakeEmbeddingProvider(), FakeIndexSink()
        embed(tmp_path, held(), embedder, sink)
        before, chunks_before, writes = dict(sink.documents), dict(sink.chunks), sink.writes

        report = embed(
            tmp_path,
            held(
                {"INC-4822": "# INC-4822\n\nFinance confirmed a total exposure CHF 13'000.\n"}
            ),
            embedder,
            sink,
        )

        assert report.written == 1
        assert sink.writes == writes + 1
        rewritten = ("incidents", "incidents-jira:INC-4822")
        changed = {
            key for key, document in sink.documents.items() if before.get(key) != document
        }
        assert changed == {rewritten}
        # Every other document's rows are the objects written the first time:
        # not rewritten with equal values, not written at all.
        assert all(
            sink.chunks[key] is chunks_before[key] for key in chunks_before if key != rewritten
        )
        assert [chunk.text for chunk in sink.chunks[rewritten]] == [
            "Finance confirmed a total exposure CHF 13'000."
        ]

    def test_a_tombstoned_document_is_removed(self, tmp_path: Path):
        """Row 3 — the one where `handover-note.md` left its folder (R2.7)."""
        embedder, sink = FakeEmbeddingProvider(), FakeIndexSink()
        embed(tmp_path, held(), embedder, sink)
        active = [document for document in held() if document.key != "handover-note.md"]

        report = embed(tmp_path, active, embedder, sink)

        assert report.removed == 1
        assert "incidents-manual:handover-note.md" not in sink.held("incidents")
        assert ("incidents", "incidents-manual:handover-note.md") not in sink.chunks
        assert report.line.endswith("· 0 written · 1 removed")

    def test_a_document_the_ledger_still_holds_keeps_its_rows(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, counter-example — the one whose fetch failed at the last sync (R2.23).

        Through the ledger: `INC-4822` is owed, its row left as it was, so the
        index is handed it unchanged and nothing about it is written or removed.
        """
        index = FakeIndexSink()
        synced = synced_workspace(
            workspace, monkeypatch, embedder=FakeEmbeddingProvider(), index=index
        )
        assert _cli(synced, monkeypatch, "embed", INDEX).exit_code == 0
        tracker = Troubled(SYNCED_ISSUES, refuse={"INC-4822"})
        register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: tracker)
        _cli(synced, monkeypatch, "sync", PIPELINE)

        result = _cli(synced, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1].endswith("· 0 written · 0 removed")
        assert "incidents-jira:INC-4822" in index.held(INDEX)

    def test_an_index_emptied_by_hand_is_rebuilt_from_the_cache(self, tmp_path: Path):
        """Row 5, counter-example — the one whose tables were emptied by hand.

        The index is derived data: everything is written again, and the model
        is asked nothing, because every vector is cached.
        """
        embedder, sink = FakeEmbeddingProvider(), FakeIndexSink()
        embed(tmp_path, held(), embedder, sink)
        asked = embedder.calls
        sink.documents.clear()
        sink.chunks.clear()

        report = embed(tmp_path, held(), embedder, sink)

        assert report.written == 4
        assert embedder.calls == asked
        assert len(sink.held_chunks("incidents")) == 4

    def test_a_document_that_fails_to_convert_keeps_its_rows(
        self, workspace: Path, monkeypatch
    ):
        """Row 6, counter-example — the one whose new snapshot cannot be converted (R8.6).

        Removed, one converter's failure would take a held document out of
        search without a word. Kept, and named.
        """
        index = FakeIndexSink()
        synced = synced_workspace(
            workspace, monkeypatch, embedder=FakeEmbeddingProvider(), index=index
        )
        assert _cli(synced, monkeypatch, "embed", INDEX).exit_code == 0
        before = index.documents[(INDEX, "incidents-jira:INC-4822")]
        tracker = Troubled(SYNCED_ISSUES, garble={"INC-4822"})
        register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: tracker)
        assert _cli(synced, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(synced, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert any(
            line.startswith("INC-4822: not converted, its rows are kept: ") for line in lines
        ), result.output
        assert lines[-1].endswith("· 0 written · 0 removed")
        assert index.documents[(INDEX, "incidents-jira:INC-4822")] is before


class Troubled(IssueTracker):
    """An issue tracker refusing some fetches, and answering others with bytes no
    converter can read."""

    def __init__(self, issues, *, refuse=frozenset(), garble=frozenset()) -> None:
        super().__init__(issues)
        self.refuse, self.garble = set(refuse), set(garble)

    def fetch(self, key: str) -> RawItem:
        if key in self.refuse:
            raise RuntimeError(f"GET {key} answered 503")
        if key in self.garble:
            return RawItem(
                key=key,
                payload=bytes([0xFF, 0xFE]) + b" not UTF-8",
                media_type=self.media_type,
                remote_version=None,
            )
        return super().fetch(key)
