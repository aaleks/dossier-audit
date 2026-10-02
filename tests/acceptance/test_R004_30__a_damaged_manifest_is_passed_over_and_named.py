"""R4.30 — a command looking for a past run passes over a manifest it cannot
read, and names it.

One manifest cut short stopped `run`, `run --plan`, `eval`, `embed` and
`status` with a traceback: each read every newer manifest, of any pipeline,
before it asked which pipeline a run was. Only `gc` passed over one (R16.11).
Here the scoring example is run twice, and the second run's manifest is cut
in half, as a process killed while writing it would have left it before
R4.29. Every command goes on with the run it can read, and says which file it
passed over.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, _cli
from tests.scoring_example import PIPELINE

pytestmark = pytest.mark.outer_loop

PASSED_OVER = re.compile(r"^  passed over: runs/(\S+)/manifest\.json cannot be read: \S")


@pytest.fixture
def damaged(two_runs: tuple[Path, str, str]) -> tuple[Path, str, str]:
    """The two runs, the second's manifest cut in half."""
    workspace, first, second = two_runs
    manifest = workspace / "runs" / second / "manifest.json"
    whole = manifest.read_text(encoding="utf-8")
    manifest.write_text(whole[: len(whole) // 2], encoding="utf-8")
    return workspace, first, second


def _passed_over(result) -> list[str]:
    return [
        found.group(1)
        for line in result.stderr.splitlines()
        if (found := PASSED_OVER.match(line))
    ]


class TestADamagedManifestIsPassedOverAndNamed:
    """R4.30 — every command goes on with the runs it can read, naming the one it cannot."""

    def test_a_plan_is_compared_with_the_newest_run_it_can_read(self, damaged, monkeypatch):
        """Row 1 — the one asked for a plan."""
        workspace, first, second = damaged

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == [second]
        assert f"compared against {first}" in result.stdout

    def test_eval_scores_the_newest_run_it_can_read(self, damaged, monkeypatch):
        """Row 2 — the one scored: as it scores the first run with the second gone."""
        workspace, first, second = damaged
        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
        aside = workspace / "aside"
        shutil.move(workspace / "runs" / second, aside)
        alone = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == alone.exit_code == 0, result.output
        assert _passed_over(result) == [second]
        assert result.stdout == alone.stdout

    def test_status_names_the_newest_run_it_can_read(self, damaged, monkeypatch):
        """Row 3 — the one asked what state the pipeline is in."""
        workspace, first, second = damaged

        result = _cli(workspace, monkeypatch, "status")

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == [second]
        assert f"{PIPELINE} · latest run {first} ·" in result.stdout

    def test_a_run_goes_on(self, damaged, monkeypatch):
        """Row 4 — the one run again, every answer served from the cache."""
        workspace, first, second = damaged

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == [second]

    def test_nothing_is_named_when_every_manifest_reads(
        self, two_runs: tuple[Path, str, str], monkeypatch
    ):
        """Row 5, counter-example — the one with nothing cut short."""
        workspace, first, second = two_runs

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == []
        assert f"compared against {second}" in result.stdout
