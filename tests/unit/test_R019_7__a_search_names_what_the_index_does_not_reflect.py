"""R19.7 — a search names how many held documents the index does not hold as
they are held.

A search answers from what was last embedded. A document synced since, changed
since, or tombstoned since is invisible or out of date in it, and nothing in a
ranked list says so.
"""

from __future__ import annotations

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
