"""R19.1 — chunks are ranked by reciprocal rank fusion of their ranks by meaning
and by words.

A chunk's score is the sum, over the two lists it is in, of `1 / (60 + rank)`,
its rank counted from 1. Higher scores first; two equal scores are ordered by
chunk id, so a search lists the same order on every machine.
"""

from __future__ import annotations

from dossier.domain.search import Candidate, fused


def _chunk(chunk_id: str, document: str) -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        document_id=f"incidents-jira:{document}",
        kind="body",
        heading_path=(document,),
        text=f"{document} text",
    )


ROOT_CAUSE = _chunk("c4830-root-cause", "INC-4830")
INC_4977 = _chunk("c4977-body", "INC-4977")
INC_4901 = _chunk("c4901-body", "INC-4901")


class TestChunksAreRankedByReciprocalRankFusion:
    """R19.1 — 1 / (60 + rank), summed over the lists a chunk is in."""

    def test_found_both_ways_outweighs_leading_one_way(self):
        """Row 1 — the one where INC-4830's root cause is in both lists."""
        ranked = fused(meaning=[ROOT_CAUSE, INC_4977], words=[INC_4901, ROOT_CAUSE])

        assert [(r.candidate, r.score) for r in ranked] == [
            (ROOT_CAUSE, 1 / 61 + 1 / 62),
            (INC_4901, 1 / 61),
            (INC_4977, 1 / 62),
        ]
        assert (ranked[0].meaning, ranked[0].words) == (1, 2)
        assert (ranked[2].meaning, ranked[2].words) == (2, None)

    def test_a_chunk_found_only_by_words_still_ranks(self):
        """Row 2 — the one where the query is an incident key, near nothing in meaning."""
        first, second = _chunk("c4830-a", "INC-4830"), _chunk("c4830-b", "INC-4830")

        ranked = fused(meaning=[], words=[first, second])

        assert [(r.candidate, r.score) for r in ranked] == [(first, 1 / 61), (second, 1 / 62)]

    def test_equal_scores_are_ordered_by_chunk_id(self):
        """Row 3 — the one where one leads by meaning and one by words."""
        later, earlier = _chunk("c-b", "INC-4977"), _chunk("c-a", "INC-4901")

        for meaning, words in (([later], [earlier]), ([earlier], [later])):
            ranked = fused(meaning=meaning, words=words)

            assert [r.candidate for r in ranked] == [earlier, later]
            assert ranked[0].score == ranked[1].score == 1 / 61

    def test_a_chunk_in_neither_list_is_not_ranked(self):
        """Row 4, counter-example — the one no list returned."""
        ranked = fused(meaning=[ROOT_CAUSE], words=[])

        assert [r.candidate for r in ranked] == [ROOT_CAUSE]
        assert all(r.score > 0 for r in ranked)
        assert fused(meaning=[], words=[]) == ()
