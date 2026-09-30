"""R11.31 — an eval's record names the documents it did not score, as the
terminal did.

R7.52 has `eval` count a failed document in its headline and name it on a
`not scored` line. Its record held the count and nothing else: a description
saying `4 documents` over a run it scored three of, and a `scores.json` with
nothing saying why the fourth was missing. R11.27 for an eval.

Through the CLI, with tracking on and a `FakeTracker`, over R7.52's run: the
scoring example's four incidents, `INC-4822` failing `extract` after its retry.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.acceptance.test_R007_52__eval_scores_a_run_in_which_a_document_failed import (
    FAILED,
    REASON,
    _eval,
    _run,
)
from tests.fakes import FakeTracker


def _recorded(workspace: Path, monkeypatch, *, failing: str | None):
    """R7.52 row 1's eval, or one over a run that failed nothing; its record."""
    _run(workspace, monkeypatch, failing=failing)
    tracker = FakeTracker()

    result = _eval(workspace, monkeypatch, tracker=tracker)

    assert result.exit_code == 0, result.output
    (run,) = tracker.runs
    return run


def _gold_line(run) -> str:
    return next(
        line
        for line in run.tags["mlflow.note.content"].splitlines()
        if line.startswith("gold ")
    )


class TestAnEvalRecordsWhatItDidNotScore:
    """R11.31 — the record says what the terminal said about what was not scored."""

    def test_the_description_counts_what_was_scored(self, workspace: Path, monkeypatch):
        """Row 1 — the one whose description said `4 documents` over three scored."""
        run = _recorded(workspace, monkeypatch, failing=FAILED)

        assert _gold_line(run).endswith(" · 3 of 4 documents"), _gold_line(run)

    def test_the_scores_name_the_document_not_scored(self, workspace: Path, monkeypatch):
        """Row 2 — the one where `scores.json` says why INC-4822 has no entries."""
        run = _recorded(workspace, monkeypatch, failing=FAILED)

        scores = json.loads(run.artifacts["scores.json"])
        assert scores["not_scored"] == [
            {"document": FAILED, "step": "extract", "reason": REASON}
        ]
        assert FAILED not in {entry["document"] for entry in scores["scores"]}

    def test_an_eval_that_scored_everything_says_so(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one where nothing failed, and the list is there."""
        run = _recorded(workspace, monkeypatch, failing=None)

        assert _gold_line(run).endswith(" · 4 documents"), _gold_line(run)
        assert json.loads(run.artifacts["scores.json"])["not_scored"] == []
