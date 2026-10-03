"""R22.8 — `--gold` with a query, a reader, `--where`, `--chunks` or `--limit`
is refused, naming both.

Each would change what is measured: the gold's files are the queries and name
their readers, and the measures are of ten documents, unfiltered. Refused before
anything is read, so an empty workspace is enough; the counter-example is the
one measured, over R19.12's workspace.
"""

from __future__ import annotations

from pathlib import Path

import pytest
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

# R19.12's workspace, its fixtures shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)

READERS = "each query names its readers"
MEASURED = "it changes what is measured"


@pytest.mark.parametrize(
    ("options", "line"),
    [
        (
            (searched.QUERY, "--gold", GOLD),
            "--gold cannot be combined with a query: the gold set's files are the queries",
        ),
        (("--gold", GOLD, "--as", "sre"), f"--gold cannot be combined with --as: {READERS}"),
        (
            ("--gold", GOLD, "--all-readers"),
            f"--gold cannot be combined with --all-readers: {READERS}",
        ),
        (
            ("--gold", GOLD, "--where", "component=checkout"),
            f"--gold cannot be combined with --where: {MEASURED}",
        ),
        (("--gold", GOLD, "--chunks"), f"--gold cannot be combined with --chunks: {MEASURED}"),
        (
            ("--gold", GOLD, "--limit", "5"),
            f"--gold cannot be combined with --limit: {MEASURED}",
        ),
    ],
    ids=["a query", "--as", "--all-readers", "--where", "--chunks", "--limit"],
)
def test_gold_with_an_option_that_changes_the_measure_is_refused(
    workspace: Path, monkeypatch, options: tuple[str, ...], line: str
):
    """Rows 1 to 3 — the ones combining `--gold` with what its files decide."""
    result = _cli(workspace, monkeypatch, "search", searched.INDEX, *options)

    assert result.exit_code == 2, result.output
    assert result.stderr.splitlines() == [line]


def test_gold_with_json_is_measured(embedded: Path, monkeypatch):
    """Row 4, counter-example — the one asking for the measures as JSON."""
    write_gold(embedded, {INC_4830: 2})

    result = measure(embedded, monkeypatch, "--json")

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("{")


def test_neither_a_query_nor_gold_is_refused(workspace: Path, monkeypatch):
    """Row 5 — the one given only an index."""
    result = _cli(workspace, monkeypatch, "search", searched.INDEX)

    assert result.exit_code == 2, result.output
    assert result.stderr.splitlines() == ["a query is required unless --gold is given"]
