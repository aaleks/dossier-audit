"""R19.5 — `--as READER` keeps only the chunks that reader may read, and a
search without it says it is not filtered.

The filtering is the index's (a chunk's `acl` must name the reader); what a
reader may be, and what the first line says, are decided here.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance import test_R019_8__search_lists_what_answers_the_query as searched
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import INDEX, PIPELINE

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


class TestAsReaderThroughTheCommand:
    """R19.5 — the reader asked of the index, said on the first line, or refused."""

    def test_a_declared_reader_is_asked_and_said(self, embedded: Path, monkeypatch, index):
        """Row 1 — the one as `incident-response`."""
        result = _search(embedded, monkeypatch, "--as", "incident-response")

        assert result.exit_code == 0, result.output
        assert index.searches[-1]["reader"] == "incident-response"
        assert result.stdout.splitlines()[0] == (f"{INDEX} · 1 document · as incident-response")

    def test_no_reader_is_said(self, embedded: Path, monkeypatch, index):
        """Row 3 — the one with no `--as`."""
        result = _search(embedded, monkeypatch)

        assert index.searches[-1]["reader"] is None
        assert result.stdout.splitlines()[0].endswith(" · not filtered by reader")

    def test_a_reader_no_source_declares_is_refused_before_the_model_is_asked(
        self, embedded: Path, monkeypatch, embedder, index
    ):
        """Row 4, counter-example — the one with a typo."""
        before = embedder.calls

        result = _search(embedded, monkeypatch, "--as", "incident-responce")

        assert result.exit_code == 2, result.output
        assert (
            f"no source of {PIPELINE} declares incident-responce as a reader; "
            "they declare incident-response"
        ) in result.stderr
        assert embedder.calls == before
        assert index.searches == []
