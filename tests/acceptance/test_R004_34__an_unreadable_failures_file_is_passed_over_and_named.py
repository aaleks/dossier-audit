"""R4.34 — a command looking for a past run passes over one whose `failures.json`
it cannot read, and names it.

R4.30 passed over a manifest cut short. A `failures.json` cut short still
stopped `run --plan`, `eval` and `status` with a traceback, and `status` exited
1, which R17.6 does not allow. Here the scoring example is run twice, and the
second run's `failures.json` is cut short, as it was before R4.29 wrote it
whole; `embed` is shown on R18.11's workspace, as R4.33 shows it. Every
command goes on with the run it can read, and says which file it passed over;
a replay of the damaged run is refused by name.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from tests.acceptance import test_R018_11__embed_carries_the_runs_record as carried
from tests.acceptance.conftest import GOLD, _cli
from tests.scoring_example import ANSWERS, PIPELINE, RoutedModel

PASSED_OVER = re.compile(r"^  passed over: runs/(\S+)/failures\.json cannot be read: \S")
CUT_SHORT = '[{"step": '

# R18.11's workspace, its fixtures shared rather than copied, as R4.33's are.
issues, embedder, index, run_once = (
    carried.issues,
    carried.embedder,
    carried.index,
    carried.run_once,
)


@pytest.fixture
def damaged(two_runs: tuple[Path, str, str]) -> tuple[Path, str, str]:
    """The two runs, the second's `failures.json` cut short."""
    workspace, first, second = two_runs
    (workspace / "runs" / second / "failures.json").write_text(CUT_SHORT, encoding="utf-8")
    return workspace, first, second


def _passed_over(result) -> list[str]:
    return [
        found.group(1)
        for line in result.stderr.splitlines()
        if (found := PASSED_OVER.match(line))
    ]


class TestAnUnreadableFailuresFileIsPassedOverAndNamed:
    """R4.34 — every command goes on with the runs it can read, naming the one it cannot."""

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
        """Row 3 — the one asked what state the pipeline is in, which exits 0 (R17.6)."""
        workspace, first, second = damaged

        result = _cli(workspace, monkeypatch, "status")

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == [second]
        assert f"{PIPELINE} · latest run {first} ·" in result.stdout

    def test_a_replay_of_the_damaged_run_is_refused_by_name(self, damaged, monkeypatch):
        """Row 4 — it cannot reproduce what the run failed, and substitutes nothing (R4.7)."""
        workspace, first, second = damaged

        result = _cli(workspace, monkeypatch, "run", "--replay", f"runs/{second}/")

        assert result.exit_code == 2, result.output
        assert "failures.json cannot be read: " in result.stderr
        assert not (workspace / "runs" / second / "replays").exists()

    def test_a_run_goes_on(self, damaged, monkeypatch):
        """Row 5 — the one run again, every answer served from the cache."""
        workspace, first, second = damaged

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == [second]

    def test_embed_carries_the_newest_run_it_can_read(self, run_once: Path, monkeypatch, index):
        """Row 6 — the one embedded: `INC-4830`'s values come from the first run."""
        import dossier.cli.bootstrap as cli

        first = carried._latest_run(run_once)
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
        assert _cli(run_once, monkeypatch, "run", PIPELINE).exit_code == 0
        second = carried._latest_run(run_once)
        assert second != first
        (run_once / "runs" / second / "failures.json").write_text(CUT_SHORT, encoding="utf-8")

        result = _cli(run_once, monkeypatch, "embed", carried.INDEX)

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == [second]
        document = carried._document(index)
        assert document.run_id == first
        assert document.values == {
            "component": "checkout",
            "failure_category": "certificate-expiry",
        }

    def test_nothing_is_named_when_every_failures_file_reads(
        self, two_runs: tuple[Path, str, str], monkeypatch
    ):
        """Row 7, counter-example — the one with nothing cut short."""
        workspace, first, second = two_runs

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == []
        assert f"compared against {second}" in result.stdout
