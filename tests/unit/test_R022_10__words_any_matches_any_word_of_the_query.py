"""R22.10 — `--words any` makes a measured search's words list match a chunk
holding any word of the query, rather than every word.

Spec 019's question 2. The query's words are joined with `or`, which
`websearch_to_tsquery` reads as either; a quoted phrase stays one. Only the
words list changes: the query's vector is the same. Over R19.12's workspace,
whose fake index records the words each search asked with.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance import (
    test_R019_12__search_lists_what_answers_the_query_for_its_readers as searched,
)
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R022_7__search_gold_prints_each_querys_measures import (
    GOLD,
    INC_4830,
    measure,
    write_gold,
)
from tests.unit.test_R011_35__a_search_is_one_trace import _tracked

from dossier.domain.relevance import any_words

# R19.12's workspace, its fixtures shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)

ANY = "certificate or expired or at or checkout"


class TestWordsAnyMatchesAnyWordOfTheQuery:
    """R22.10 — `or` between the words, a phrase kept whole, the vector unchanged."""

    def test_the_words_are_joined_with_or(self):
        """Row 1 — the one asking for any word of the spec's query."""
        assert any_words("certificate expired at checkout") == ANY

    def test_a_quoted_phrase_stays_one(self):
        """Row 2 — the one with a phrase and a word."""
        assert (
            any_words('"expired certificate" checkout') == '"expired certificate" or checkout'
        )

    def test_a_measurement_asks_with_any_word_and_the_same_vector(
        self, embedded: Path, monkeypatch, index, embedder
    ):
        """Row 1, through the command — the words list asked with `or`, the vector unchanged."""
        write_gold(embedded, {INC_4830: 2})
        before = len(index.searches)
        embedded_before = list(embedder.texts)

        result = measure(embedded, monkeypatch, "--words", "any")

        assert result.exit_code == 0, result.output
        assert [asked["words"] for asked in index.searches[before:]] == [ANY]
        # The query's vector was asked for as a plain search asks for it: the
        # instruction and the query as written, or served from the cache.
        assert all(searched.QUERY in text for text in embedder.texts[len(embedded_before) :])
        assert not any(ANY in text for text in embedder.texts)

    def test_the_words_are_a_param_and_said_first(self, embedded: Path, monkeypatch):
        """Row 3 — the same, with tracking on."""
        write_gold(embedded, {INC_4830: 2})
        tracker = _tracked(monkeypatch)

        result = measure(embedded, monkeypatch, "--words", "any")

        assert result.exit_code == 0, result.output
        assert " · any word · " in result.stdout.splitlines()[0]
        (run,) = tracker.runs
        assert run.params["words"] == "any"

    def test_by_default_every_word_is_required(self, embedded: Path, monkeypatch, index):
        """Row 4, counter-example — the one measured as search asks."""
        write_gold(embedded, {INC_4830: 2})
        before = len(index.searches)
        tracker = _tracked(monkeypatch)

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        assert [asked["words"] for asked in index.searches[before:]] == [searched.QUERY]
        assert "word" not in result.stdout.splitlines()[0]
        (run,) = tracker.runs
        assert run.params["words"] == "all"

    def test_a_search_is_refused_any_word(self, workspace: Path, monkeypatch):
        """Row 5 — the one asking a plain search for any word."""
        result = _cli(
            workspace, monkeypatch, "search", searched.INDEX, searched.QUERY, "--words", "any"
        )

        assert result.exit_code == 2, result.output
        assert result.stderr.splitlines() == [
            "--words needs --gold: it measures a variant, and search requires every word"
        ]

    def test_a_word_mode_neither_all_nor_any_is_refused(self, workspace: Path, monkeypatch):
        """Row 6 — the one asking for `some`."""
        result = _cli(
            workspace, monkeypatch, "search", searched.INDEX, "--gold", GOLD, "--words", "some"
        )

        assert result.exit_code == 2, result.output
        assert result.stderr.splitlines() == ["--words is all or any"]
