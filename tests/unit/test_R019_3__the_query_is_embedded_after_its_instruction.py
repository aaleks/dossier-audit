"""R19.3 — the query is embedded with the index's model, after the declared
instruction, and only on a cache miss.

Qwen3-Embedding is trained with an instruction on the query and none on the
document; its model card puts the cost of leaving it out at 1% to 5% of
retrieval quality. The format is the card's: `Instruct: <instruction>`, a
newline, and `Query:<query>`.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance import (
    test_R019_12__search_lists_what_answers_the_query_for_its_readers as searched,
)
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import INDEX

from dossier.domain.search import DEFAULT_INSTRUCTION, query_text

QUERY = "certificate expired at checkout"


class TestTheQueryIsEmbeddedAfterItsInstruction:
    """R19.3 — the text a query is embedded as."""

    def test_the_default_instruction_comes_first(self):
        """Row 1 — the one with no `query_instruction:`."""
        assert DEFAULT_INSTRUCTION == (
            "Given a question about incidents, retrieve the passages of incident "
            "records and documents that answer it"
        )
        assert query_text(QUERY, instruction=None) == (
            f"Instruct: {DEFAULT_INSTRUCTION}\nQuery:{QUERY}"
        )

    def test_a_declared_instruction_replaces_the_default(self):
        """Row 2 — the one declaring its own."""
        instruction = "Find the runbook that says what to do"

        assert query_text(QUERY, instruction=instruction) == (
            f"Instruct: {instruction}\nQuery:{QUERY}"
        )

    def test_an_empty_instruction_embeds_the_query_as_typed(self):
        """Row 4, counter-example — the one for a model trained without one."""
        assert query_text(QUERY, instruction="") == QUERY


# R19.12's workspace, synced, run and embedded, the index a fake; its fixtures
# shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)


def _search(workspace: Path, monkeypatch, *more: str):
    return _cli(
        workspace, monkeypatch, "search", INDEX, searched.QUERY, "--as", searched.READER, *more
    )


class TestTheQueryIsEmbeddedOnce:
    """R19.3 rows 1 and 3 — after its instruction, and only on a cache miss."""

    def test_the_same_search_again_asks_no_model(self, embedded: Path, monkeypatch, embedder):
        """Row 3 — the one asked twice."""
        before = embedder.calls

        assert _search(embedded, monkeypatch).exit_code == 0
        assert embedder.calls == before + 1
        assert embedder.texts[-1] == f"Instruct: {DEFAULT_INSTRUCTION}\nQuery:{searched.QUERY}"
        assert _search(embedded, monkeypatch).exit_code == 0

        assert embedder.calls == before + 1
