"""R19.11 — a search names its readers, or asks for every chunk with
`--all-readers`; with neither, it is refused before the model is asked.

The connection string reads every row, so the application holding it is what
keeps readers apart. An agent searching for someone that forgot `--as` gets an
error, not every chunk; asking for every chunk is a choice, and says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance import (
    test_R019_12__search_lists_what_answers_the_query_for_its_readers as searched,
)
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import INDEX

from dossier.domain.search import ReadersRefused, header, readers_for

DECLARED = frozenset({"incident-response", "sre"})
BOTH = "--as and --all-readers contradict: name the readers, or ask for every chunk"


def _neither(declared: str) -> str:
    return (
        f"name the readers this search is for with --as READER ({declared}), "
        "or search every chunk with --all-readers"
    )


class TestASearchNamesItsReaders:
    """R19.11 — the readers named, every chunk asked for, or a refusal."""

    def test_neither_is_refused(self):
        """Row 1 — the one that names no reader and does not ask for every chunk."""
        with pytest.raises(ReadersRefused) as refused:
            readers_for((), all_readers=False, declared=DECLARED, pipeline="incident-audit")

        assert str(refused.value) == _neither("incident-response, sre")

    def test_every_chunk_is_asked_for_and_said(self):
        """Row 2 — the one with `--all-readers`."""
        assert (
            readers_for((), all_readers=True, declared=DECLARED, pipeline="incident-audit")
            is None
        )
        assert header("incidents", found=2, readers=None, chunks=False) == (
            "incidents · 2 documents · not filtered by reader"
        )

    def test_both_contradict(self):
        """Row 3, counter-example — the one with `--as sre --all-readers`."""
        with pytest.raises(ReadersRefused) as refused:
            readers_for(
                ("sre",), all_readers=True, declared=DECLARED, pipeline="incident-audit"
            )

        assert str(refused.value) == BOTH


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


class TestThroughTheCommand:
    """R19.11 — refused before the model is asked, or every chunk searched and said."""

    def test_neither_is_refused_before_the_model_is_asked(
        self, embedded: Path, monkeypatch, embedder, index
    ):
        """Row 1 — the one an agent sends when it forgets `--as`."""
        before = embedder.calls

        result = _search(embedded, monkeypatch)

        assert result.exit_code == 2, result.output
        assert _neither(searched.READER) in result.stderr
        assert embedder.calls == before
        assert index.searches == []

    def test_every_chunk_is_searched_and_said(self, embedded: Path, monkeypatch, index):
        """Row 2 — the one with `--all-readers`."""
        result = _search(embedded, monkeypatch, "--all-readers")

        assert result.exit_code == 0, result.output
        assert index.searches[-1]["readers"] is None
        assert result.stdout.splitlines()[0] == f"{INDEX} · 1 document · not filtered by reader"

    def test_both_are_refused_before_the_model_is_asked(
        self, embedded: Path, monkeypatch, embedder, index
    ):
        """Row 3, counter-example — the one naming a reader and every chunk at once."""
        before = embedder.calls

        result = _search(embedded, monkeypatch, "--as", searched.READER, "--all-readers")

        assert result.exit_code == 2, result.output
        assert BOTH in result.stderr
        assert embedder.calls == before
        assert index.searches == []
