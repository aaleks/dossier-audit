"""R4.31 — `--plan` compares against the latest run that finished, and names
each newer run that stopped before it ended.

A run writes its manifest before it asks anything, and the plan compared
against the latest manifest. A run killed after one of four notes then printed
`extract: cached` for a step the next run asked three times (R4.12), found live
in exercise 24. Here a run is stopped the way a kill leaves one on disk: its
manifest written, the first document's records written, no `failures.json`.
The suffixes are pinned so the ids in a failure read in order; a run made in
the same second as another is filed after it anyway (R0.15).
"""

from __future__ import annotations

import re
from itertools import count
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    Model,
    _edit_prompt,
    _workspace,
)
from tests.scoring_example import PIPELINE

STOPPED = re.compile(
    r"^  passed over: runs/(\S+)/ has no failures\.json: "
    r"it stopped before it ended, or has not ended yet$"
)


def _run(workspace: Path, monkeypatch) -> str:
    """One run; its id. Served from cache when nothing changed, as row 1's second is."""
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return re.search(r"^run (\S+)", result.output, re.MULTILINE).group(1)


def _runs(workspace: Path, monkeypatch, *, edited: bool = False, n: int = 2) -> list[str]:
    """`n` runs of the scoring example, oldest first; the prompt edited before the second."""
    suffixes = count(1)
    monkeypatch.setattr("dossier.cli.run.token_hex", lambda n: f"{next(suffixes):04x}")
    _workspace(workspace, monkeypatch)
    runs = [_run(workspace, monkeypatch)]
    for _ in range(n - 1):
        if edited:
            _edit_prompt(workspace)
        runs.append(_run(workspace, monkeypatch))
    return runs


def _stop(workspace: Path, run: str) -> None:
    """Leave `run` as a kill after its first document would: no `failures.json`."""
    directory = workspace / "runs" / run
    (directory / "failures.json").unlink()
    for record in sorted((directory / "extract").iterdir())[2:]:
        record.unlink()


def _plan(workspace: Path, monkeypatch):
    result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")
    assert result.exit_code == 0, result.output
    return result


def _passed_over(result) -> list[str]:
    return [
        found.group(1) for line in result.stderr.splitlines() if (found := STOPPED.match(line))
    ]


class TestAPlanPassesOverARunThatStopped:
    """R4.31 — `cached` is promised only against a run that finished."""

    def test_a_stopped_run_is_passed_over_for_the_one_before_it(self, workspace, monkeypatch):
        """Row 1 — the one run twice with nothing changed, the second stopped."""
        first, second = _runs(workspace, monkeypatch)
        _stop(workspace, second)

        result = _plan(workspace, monkeypatch)

        assert _passed_over(result) == [second]
        assert f"compared against {first}" in result.stdout
        assert "  extract: cached" in result.stdout.splitlines()

    def test_the_change_since_the_finished_run_is_what_the_plan_says(
        self, workspace, monkeypatch
    ):
        """Row 2 — the one whose prompt was edited before the run that stopped."""
        first, second = _runs(workspace, monkeypatch, edited=True)
        _stop(workspace, second)

        result = _plan(workspace, monkeypatch)

        assert _passed_over(result) == [second]
        assert f"compared against {first}" in result.stdout
        assert "! extract: prompt changed" in result.stdout.splitlines()

    def test_a_lone_run_that_stopped_leaves_nothing_to_compare_against(
        self, workspace, monkeypatch
    ):
        """Row 3 — the one whose only run stopped."""
        (only,) = _runs(workspace, monkeypatch, n=1)
        _stop(workspace, only)

        result = _plan(workspace, monkeypatch)

        assert _passed_over(result) == [only]
        assert "no previous run to compare against" in result.stdout.splitlines()
        assert "! extract: new" in result.stdout.splitlines()

    def test_a_run_that_finished_is_the_one_compared_against(self, workspace, monkeypatch):
        """Row 4, counter-example — the one whose second run finished, failing nothing."""
        _, second = _runs(workspace, monkeypatch)

        result = _plan(workspace, monkeypatch)

        assert _passed_over(result) == []
        assert "passed over" not in result.stderr
        assert f"compared against {second}" in result.stdout
