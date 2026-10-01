"""R19.5 — `--as READER` keeps only the chunks that reader may read, and a
search without it says it is not filtered.

The filtering is the index's (a chunk's `acl` must name the reader); what a
reader may be, and what the first line says, are decided here.
"""

from __future__ import annotations

from dossier.domain.search import header, reader_refusal

READERS = frozenset({"incident-response", "sre"})


class TestAsReaderKeepsWhatTheReaderMayRead:
    """R19.5 — a reader the sources declare, or none, said so."""

    def test_a_declared_reader_is_searched_as(self):
        """Rows 1 and 2 — the ones as `incident-response` and as `sre`."""
        for reader in ("incident-response", "sre"):
            assert reader_refusal(reader, declared=READERS, pipeline="incident-audit") is None
        assert header("incidents", found=1, reader="incident-response", chunks=False) == (
            "incidents · 1 document · as incident-response"
        )

    def test_no_reader_says_the_search_was_not_filtered(self):
        """Row 3 — the one with no `--as`."""
        assert reader_refusal(None, declared=READERS, pipeline="incident-audit") is None
        assert header("incidents", found=2, reader=None, chunks=False) == (
            "incidents · 2 documents · not filtered by reader"
        )

    def test_chunks_are_counted_as_chunks(self):
        """The one asked for chunks."""
        assert header("incidents", found=1, reader=None, chunks=True) == (
            "incidents · 1 chunk · not filtered by reader"
        )

    def test_a_reader_no_source_declares_is_refused(self):
        """Row 4, counter-example — the one with a typo, which would find nothing."""
        assert reader_refusal(
            "incident-responce", declared=READERS, pipeline="incident-audit"
        ) == (
            "no source of incident-audit declares incident-responce as a reader; "
            "they declare incident-response, sre"
        )
