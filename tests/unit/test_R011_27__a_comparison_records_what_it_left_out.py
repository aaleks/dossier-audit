"""R11.27 — a comparison's record names the documents it left out, as the
terminal did.

R7.54 leaves a document one run failed out of both runs' scores, and R7.55
names it. The record holds the deltas (R11.8), a description (R11.12) and the
table printed (R11.14). Without this rule, all three would describe a comparison
over `4 documents` that scored three.

Through the CLI, with tracking on and a `FakeTracker`, over R7.54's two runs:
the scoring example, the prompt edited between them, and `b` failing `INC-4822`
at `extract` after its retry.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_52__eval_scores_a_run_in_which_a_document_failed import (
    GOLD,
    URI,
)
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    Model,
    _two_runs,
    _workspace,
)
from tests.fakes import FakeTracker, NoModelClient
from tests.scoring_example import PIPELINE

MARK = "   <- regression"


def _recorded(workspace: Path, monkeypatch, *, failing: str | None):
    """R7.54 row 1's comparison, or one that failed nothing; its record and its output."""
    import dossier.cli.bootstrap as cli

    _workspace(workspace, monkeypatch)
    a, b = _two_runs(workspace, monkeypatch, Model(), Model(failing=failing))
    tracker = FakeTracker()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)

    result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b)

    assert result.exit_code == 0, result.output
    (run,) = tracker.runs
    return run, result.output


class TestAComparisonRecordsWhatItLeftOut:
    """R11.27 — the record says what the terminal said about what was left out."""

    def test_the_run_that_failed_a_document_has_a_failed_metric(
        self, workspace: Path, monkeypatch
    ):
        """Row 1 — the one where `b` failed INC-4822, and `a` failed nothing."""
        run, _ = _recorded(workspace, monkeypatch, failing="INC-4822")

        assert run.metrics["b/failed"] == 1
        assert "a/failed" not in run.metrics

    def test_the_description_counts_what_was_compared(self, workspace: Path, monkeypatch):
        """Row 2 — the one whose description says `3 of 4 documents`, as the headline does."""
        run, output = _recorded(workspace, monkeypatch, failing="INC-4822")

        described = run.tags["mlflow.note.content"]
        assert " · 3 of 4 documents" in described, described
        assert "3 of 4 documents" in output.splitlines()[0], output

    def test_the_table_holds_the_line_the_terminal_printed(self, workspace: Path, monkeypatch):
        """Row 3 — the one where `deltas.md` names INC-4822, marked as it was."""
        run, output = _recorded(workspace, monkeypatch, failing="INC-4822")

        (printed,) = [line for line in output.splitlines() if "not compared: " in line]
        assert printed.endswith(MARK), printed
        table = run.artifacts["deltas.md"].decode("utf-8").splitlines()
        assert printed.strip() in table, table

    def test_a_comparison_that_left_nothing_out_records_as_before(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, counter-example — the one where neither run failed (R11.8)."""
        run, _ = _recorded(workspace, monkeypatch, failing=None)

        assert not {"a/failed", "b/failed"} & set(run.metrics), run.metrics
        assert " · 4 documents" in run.tags["mlflow.note.content"]
        assert "not compared" not in run.artifacts["deltas.md"].decode("utf-8")
