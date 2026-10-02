"""R19.10 — `--as READER`, repeatable, keeps only the chunks one of the
readers named may read.

The filtering is the index's: a chunk's `acl` must name one of the readers,
proved live in `tests/integration/test_R019_4__postgres_search_filters.py`.
Which readers a search is for, and what the first line says, are decided here.
It supersedes R19.5, whose search without `--as` is R19.11's.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance import (
    test_R019_12__search_lists_what_answers_the_query_for_its_readers as searched,
)
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import INDEX, PIPELINE

from dossier.domain.search import ReadersRefused, header, readers_for

DECLARED = frozenset({"incident-response", "sre"})


def _readers(*named: str) -> tuple[str, ...] | None:
    return readers_for(named, all_readers=False, declared=DECLARED, pipeline="incident-audit")


class TestAsKeepsWhatANamedReaderMayRead:
    """R19.10 — the readers a search is for: each declared, each once, in order."""

    def test_one_reader(self):
        """Row 1 — the one as `incident-response`."""
        assert _readers("incident-response") == ("incident-response",)
        assert header("incidents", found=1, readers=("incident-response",), chunks=False) == (
            "incidents · 1 document · as incident-response"
        )

    def test_two_readers_are_one_search(self):
        """Row 2 — the one as `incident-response` and `sre`, in one ranked list."""
        assert _readers("incident-response", "sre") == ("incident-response", "sre")
        assert header(
            "incidents", found=2, readers=("incident-response", "sre"), chunks=False
        ) == ("incidents · 2 documents · as incident-response, sre")

    def test_each_reader_once_in_order(self):
        """Row 3 — the one naming `sre` twice, before and after `incident-response`."""
        assert _readers("sre", "incident-response", "sre") == ("incident-response", "sre")

    def test_chunks_are_counted_as_chunks(self):
        """The one asked for chunks."""
        assert header("incidents", found=1, readers=("sre",), chunks=True) == (
            "incidents · 1 chunk · as sre"
        )

    def test_a_reader_no_source_declares_is_refused(self):
        """Row 4, counter-example — the one with a typo beside a declared reader."""
        with pytest.raises(ReadersRefused) as refused:
            _readers("incident-responce", "sre")

        assert str(refused.value) == (
            "no source of incident-audit declares incident-responce as a reader; "
            "they declare incident-response, sre"
        )


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
    return _cli(workspace, monkeypatch, "search", INDEX, searched.QUERY, *more)


class TestAsThroughTheCommand:
    """R19.10 — the readers asked of the index, said on the first line, or refused."""

    def test_the_readers_named_are_asked_once_each(self, embedded: Path, monkeypatch, index):
        """Rows 1 and 3 — the one as `incident-response`, named twice."""
        result = _search(
            embedded, monkeypatch, "--as", searched.READER, "--as", searched.READER
        )

        assert result.exit_code == 0, result.output
        assert index.searches[-1]["readers"] == (searched.READER,)
        assert result.stdout.splitlines()[0] == f"{INDEX} · 1 document · as {searched.READER}"

    def test_a_reader_no_source_declares_is_refused_before_the_model_is_asked(
        self, embedded: Path, monkeypatch, embedder, index
    ):
        """Row 4, counter-example — the one with a typo beside a declared reader."""
        before = embedder.calls

        result = _search(
            embedded, monkeypatch, "--as", "incident-responce", "--as", searched.READER
        )

        assert result.exit_code == 2, result.output
        assert (
            f"no source of {PIPELINE} declares incident-responce as a reader; "
            "they declare incident-response"
        ) in result.stderr
        assert embedder.calls == before
        assert index.searches == []
