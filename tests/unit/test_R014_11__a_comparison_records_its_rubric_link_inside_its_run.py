"""R14.11 — the application half: `record_comparison` links the rubric inside its run.

A comparison opens and closes its own run (R11.8), so the link is made between
the two, or it lands on nothing. One link per field, however many sides: both
were judged with the rubric whose hash is handed in.
"""

from __future__ import annotations

from tests.fakes import FakePromptRegistry, FakeTracker

from dossier.application.eval import record_comparison
from dossier.domain.scoring import FieldTotal, compare_totals, overall

RUNS = ("20260806T142203Z-4f1a", "20260907T090000Z-bbbb")
MODEL = "gemini:gemini-3.5-flash-lite"
RUBRIC = "incident-audit.judge.root_cause"
RUBRIC_HASH = "f7a2d9c4" * 8

BEFORE = [FieldTotal(field="root_cause", correct=2, scored=4)]
AFTER = [FieldTotal(field="root_cause", correct=4, scored=4)]


def _record(tracker: FakeTracker, registry: FakePromptRegistry, **kwargs) -> None:
    record_comparison(
        tracker,
        experiment="dossier-audit/incident-audit/compare",
        pipeline="incident-audit",
        runs=RUNS,
        models=(MODEL, MODEL),
        gold="gold/incidents",
        gold_files={},
        rows=compare_totals(BEFORE, AFTER),
        overalls=(overall(BEFORE), overall(AFTER)),
        prompt_registry=registry,
        rubric_hashes={"root_cause": RUBRIC_HASH},
        **kwargs,
    )


def _published() -> FakePromptRegistry:
    registry = FakePromptRegistry()
    registry.publish(name=RUBRIC, template="t", tags={"dossier.prompt_hash": RUBRIC_HASH})
    return registry


class TestAComparisonRecordsItsRubricLinkInsideItsRun:
    """R14.11 — the comparison's run links the rubric both sides were judged with."""

    def test_the_rubric_is_linked_once_on_the_comparison_run(self):
        """Row 1: the one with two sides and one standard."""
        tracker = FakeTracker()

        _record(tracker, _published())

        assert tracker.links == [(RUBRIC, 1)]
        assert len(tracker.runs) == 1

    def test_a_withheld_field_is_not_looked_up(self):
        """Counter-example (row 2): the one no reported figure came from."""
        registry, tracker = _published(), FakeTracker()
        registry.reads.clear()

        _record(tracker, registry, withheld={"root_cause": "stale"})

        assert registry.reads == []
        assert tracker.links == []
