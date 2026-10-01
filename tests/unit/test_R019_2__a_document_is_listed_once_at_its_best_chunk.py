"""R19.2 — a search lists documents, each once, at its best chunk's place;
`--chunks` lists the chunks.

A person looks for incidents, not fragments, and one long document must not
fill the page. `--chunks` is for when the fragments are wanted.
"""

from __future__ import annotations

from dossier.domain.search import Candidate, fused, listed


def _chunk(chunk_id: str, document: str, kind: str = "body") -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        document_id=f"incidents-jira:{document}",
        kind=kind,
        heading_path=(document,),
        text=f"{document} {chunk_id}",
    )


ROOT_CAUSE = _chunk("c4830-root-cause", "INC-4830")
RECORD = _chunk("c4830-record", "INC-4830", kind="record")
INC_4977 = _chunk("c4977-body", "INC-4977")


def _fused(*order: Candidate):
    """The chunks as fused in `order`: meaning ranks them so, words not at all."""
    return fused(meaning=list(order), words=[])


class TestADocumentIsListedOnceAtItsBestChunk:
    """R19.2 — documents by default, each at its best chunk."""

    def test_each_document_once_at_its_best_chunk(self):
        """Row 1 — the one where INC-4830 has two chunks in the list."""
        shown = listed(_fused(ROOT_CAUSE, INC_4977, RECORD), limit=10)

        assert [r.candidate for r in shown] == [ROOT_CAUSE, INC_4977]

    def test_the_limit_counts_documents(self):
        """Row 2 — the one cut at one document."""
        shown = listed(_fused(ROOT_CAUSE, INC_4977, RECORD), limit=1)

        assert [r.candidate for r in shown] == [ROOT_CAUSE]

    def test_chunks_lists_the_chunks_as_fused(self):
        """Row 3 — the one asked for chunks, INC-4830 twice."""
        shown = listed(_fused(ROOT_CAUSE, INC_4977, RECORD), limit=10, chunks=True)

        assert [r.candidate for r in shown] == [ROOT_CAUSE, INC_4977, RECORD]

    def test_chunks_are_not_grouped_so_one_document_can_fill_the_list(self):
        """Row 4, counter-example — the one where INC-4830's two chunks lead."""
        shown = listed(_fused(ROOT_CAUSE, RECORD, INC_4977), limit=2, chunks=True)

        assert [r.candidate for r in shown] == [ROOT_CAUSE, RECORD]
