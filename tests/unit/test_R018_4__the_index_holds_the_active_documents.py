"""R18.4 — the index holds exactly the active documents of its pipeline's sources,
and writes only what changed.

The index is derived data. What it is handed is what the ledger holds active
(R2.7), and each document is written only when the hash of everything written
for it moves. Emptied by hand, it is rebuilt from the cache, asking no model.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeEmbeddingProvider, FakeIndexSink
from tests.unit.test_R018_3__a_chunk_is_embedded_only_on_a_cache_miss import (
    declaration,
)

from dossier.application.embed import ToIndex, embed_index
from dossier.domain.chunks import HeadingsChunker
from dossier.domain.hashing import content_hash
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
        before = dict(sink.documents)

        report = embed(
            tmp_path,
            held(
                {"INC-4822": "# INC-4822\n\nFinance confirmed a total exposure CHF 13'000.\n"}
            ),
            embedder,
            sink,
        )

        assert report.written == 1
        changed = {
            key for key, document in sink.documents.items() if before.get(key) != document
        }
        assert changed == {("incidents", "incidents-jira:INC-4822")}

    def test_a_tombstoned_document_is_removed(self, tmp_path: Path):
        """Row 3 — the one where `handover-note.md` left its folder (R2.7)."""
        embedder, sink = FakeEmbeddingProvider(), FakeIndexSink()
        embed(tmp_path, held(), embedder, sink)
        active = [document for document in held() if document.key != "handover-note.md"]

        report = embed(tmp_path, active, embedder, sink)

        assert report.removed == 1
        assert "incidents-manual:handover-note.md" not in sink.held("incidents")
        assert report.line.endswith("· 0 written · 1 removed")

    def test_a_document_the_ledger_still_holds_keeps_its_rows(self, tmp_path: Path):
        """Row 4, counter-example — the one whose fetch failed at the last sync (R2.23).

        Its fetch failing left the ledger's row as it was, so it is still
        handed in, unchanged, and nothing about it is written or removed.
        """
        embedder, sink = FakeEmbeddingProvider(), FakeIndexSink()
        embed(tmp_path, held(), embedder, sink)
        before = dict(sink.documents)

        report = embed(tmp_path, held(), embedder, sink)

        assert (report.written, report.removed) == (0, 0)
        assert sink.documents == before

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
