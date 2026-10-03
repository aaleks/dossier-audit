"""R22.6 — each query is searched as the readers its file names, and a judgment
of a document none of them may read is refused.

A document a query's readers may not read is never listed for them (R19.10),
so judging it relevant would count a miss the search was right to make. Over
R19.12's workspace, whose `incidents-jira` gives its documents to
`incident-response` alone, with tracking on so each query's trace says whom it
searched as (R11.35).
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance import (
    test_R019_12__search_lists_what_answers_the_query_for_its_readers as searched,
)
from tests.acceptance.test_R022_7__search_gold_prints_each_querys_measures import (
    INC_4830,
    NAME,
    measure,
    write_gold,
)
from tests.unit.test_R011_35__a_search_is_one_trace import _tracked

# R19.12's workspace, its fixtures shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)


class TestAQueryIsSearchedAsItsReaders:
    """R22.6 — the file's readers, and only documents they may read judged."""

    def test_a_query_is_searched_as_its_reader(self, embedded: Path, monkeypatch):
        """Row 1 — the one as `incident-response`."""
        write_gold(embedded, {INC_4830: 2})
        tracker = _tracked(monkeypatch)

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        (trace,) = [
            trace for trace in tracker.traces if trace.tags.get("dossier.kind") == "search"
        ]
        assert trace.inputs["readers"] == ["incident-response"]

    def test_a_judgment_its_readers_cannot_read_is_refused(self, embedded: Path, monkeypatch):
        """Row 2 — the one as `sre`, judging a document only `incident-response` may read."""
        write_gold(embedded, {INC_4830: 2}, readers=("sre",))
        tracker = _tracked(monkeypatch)

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 2, result.output
        assert result.stderr.splitlines() == [f"{NAME}.yaml: {INC_4830} is not readable by sre"]
        assert tracker.traces == [], "refused before any search"

    def test_a_query_is_searched_as_both_of_its_readers(self, embedded: Path, monkeypatch):
        """Row 3, counter-example — the one as both, one of whom may read it."""
        sources = embedded / "sources.yaml"
        sources.write_text(
            sources.read_text(encoding="utf-8").replace(
                "acl: [incident-response]", "acl: [incident-response, sre]"
            ),
            encoding="utf-8",
        )
        write_gold(embedded, {INC_4830: 2}, readers=("incident-response", "sre"))
        tracker = _tracked(monkeypatch)

        result = measure(embedded, monkeypatch)

        assert result.exit_code == 0, result.output
        (trace,) = [
            trace for trace in tracker.traces if trace.tags.get("dossier.kind") == "search"
        ]
        assert trace.inputs["readers"] == ["incident-response", "sre"]
