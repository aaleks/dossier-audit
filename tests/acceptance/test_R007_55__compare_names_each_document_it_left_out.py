"""R7.55 — `--compare` names each document it left out, with the run that
failed it, the step and the reason.

A document left out of a comparison (R7.54) is not silent, as a failed one is
not silent in an eval (R7.52). Its line ends `   <- regression` when `b` failed
a document `a` answered: the change lost it, and R7.8 flags every regression.
Decided by `a.aleks` on 2026-09-29.

The two runs of R7.54's test: the scoring example's four incidents, the prompt
edited between them so the second is asked afresh, and a document named to
fail answering prose on both attempts.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.test_R007_52__eval_scores_a_run_in_which_a_document_failed import (
    REASON,
)
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    Model,
    _compare,
    _two_runs,
    _workspace,
)

MARK = "   <- regression"


def _named(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("  not compared: ")]


class TestCompareNamesEachDocumentItLeftOut:
    """R7.55 — each document left out, named with its run, step and reason."""

    def test_a_document_the_change_lost_is_named_and_marked(self, workspace: Path, monkeypatch):
        """Row 1 — the one where `b` failed a document `a` answered."""
        _workspace(workspace, monkeypatch)
        a, b = _two_runs(workspace, monkeypatch, Model(), Model(failing="INC-4822"))

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert _named(result.output) == [
            f"  not compared: INC-4822 failed at extract in {b}: {REASON}{MARK}"
        ], result.output

    def test_a_document_both_runs_failed_is_named_for_each_and_not_marked(
        self, workspace: Path, monkeypatch
    ):
        """Row 2 — the one where the change lost nothing."""
        _workspace(workspace, monkeypatch)
        a, b = _two_runs(
            workspace, monkeypatch, Model(failing="INC-4822"), Model(failing="INC-4822")
        )

        result = _compare(workspace, monkeypatch, a, b)

        assert _named(result.output) == [
            f"  not compared: INC-4822 failed at extract in {a}: {REASON}",
            f"  not compared: INC-4822 failed at extract in {b}: {REASON}",
        ], result.output

    def test_a_document_the_change_recovered_is_named_and_not_marked(
        self, workspace: Path, monkeypatch
    ):
        """Row 3, counter-example — the one where `a` failed it and `b` answered it."""
        _workspace(workspace, monkeypatch)
        a, b = _two_runs(workspace, monkeypatch, Model(failing="INC-4822"), Model())

        result = _compare(workspace, monkeypatch, a, b)

        assert _named(result.output) == [
            f"  not compared: INC-4822 failed at extract in {a}: {REASON}"
        ], result.output

    def test_a_comparison_that_left_nothing_out_names_nothing(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, counter-example — the one where neither run failed."""
        _workspace(workspace, monkeypatch)
        a, b = _two_runs(workspace, monkeypatch, Model(), Model())

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert "not compared" not in result.output, result.output
