"""R19.7 — a search names how many held documents the index does not hold as
they are held.

A search answers from what was last embedded. A document synced since, changed
since, or tombstoned since is invisible or out of date in it, and nothing in a
ranked list says so.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance import test_R019_8__search_lists_what_answers_the_query as searched
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import INDEX, NOTE, PIPELINE

from dossier.domain.search import unreflected, unreflected_line

INDEXED = {
    "incidents-jira:INC-4821": "a3f9c1e2",
    "incidents-jira:INC-4822": "77c1b40a",
}


class TestASearchNamesWhatTheIndexDoesNotReflect:
    """R19.7 — a count of what changed since the last embed."""

    def test_a_document_synced_since_is_counted(self):
        """Row 1 — the one where INC-4901 arrived after the embed."""
        held = {**INDEXED, "incidents-jira:INC-4901": "0e52dd18"}

        assert unreflected(held=held, indexed=INDEXED) == 1
        assert unreflected_line("incidents", 1) == (
            "1 held document not in incidents as held: run dossier embed incidents"
        )

    def test_a_document_changed_since_is_counted(self):
        """Row 2 — the one where INC-4822 was re-synced at a new snapshot."""
        held = {**INDEXED, "incidents-jira:INC-4822": "0e52dd18"}

        assert unreflected(held=held, indexed=INDEXED) == 1

    def test_a_document_tombstoned_since_is_counted(self):
        """Row 3 — the one where INC-4821 is gone, its rows still in the index."""
        held = {"incidents-jira:INC-4822": "77c1b40a"}

        assert unreflected(held=held, indexed=INDEXED) == 1

    def test_the_line_counts_in_the_plural(self):
        """The one where three changed."""
        assert unreflected_line("incidents", 3) == (
            "3 held documents not in incidents as held: run dossier embed incidents"
        )

    def test_nothing_synced_since_says_nothing(self):
        """Row 4, counter-example — the one embedded after the last sync."""
        assert unreflected(held=dict(INDEXED), indexed=INDEXED) == 0
        assert unreflected_line("incidents", 0) is None


# R19.8's workspace, synced, run and embedded, the index a fake; its fixtures
# shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)


def _search(workspace: Path, monkeypatch, *more: str):
    return _cli(workspace, monkeypatch, "search", INDEX, searched.QUERY, *more)


class TestThroughTheCommand:
    """R19.7 — after the results, as the last line."""

    def test_a_document_synced_since_is_named(self, embedded: Path, monkeypatch, issues):
        """Row 1 — the one where INC-4901 arrived after the embed."""
        issues["INC-4901"] = NOTE.replace("INC-4830", "INC-4901")
        assert _cli(embedded, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _search(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[-1] == (
            f"1 held document not in {INDEX} as held: run dossier embed {INDEX}"
        )

    def test_nothing_synced_since_says_nothing(self, embedded: Path, monkeypatch):
        """Row 4, counter-example — the one embedded after the last sync."""
        result = _search(embedded, monkeypatch)

        assert "not in incidents as held" not in result.stdout
