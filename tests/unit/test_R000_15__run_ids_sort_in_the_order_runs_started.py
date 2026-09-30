"""R0.15 — a run started in the same second as a run already filed is filed
after it, so run ids sort in the order runs started.

A run is filed as `<started>-<suffix>` (R0.8), and every reader of "the latest
run" takes the last by name. The time is to the second and the suffix was drawn
at random, so two runs within one second sorted by chance. Found by the live
check that closed spec 016. The id keeps its form: when the second already holds
a run, the suffix is the one after the last used in it.

Rows 1, 2, 3 and 5 are the decision, `run_id`, handed the ids already filed.
Rows 4 and 6 are through the CLI, with the clock stopped at
`2026-08-06T14:22:03Z` and the suffixes drawn pinned, so two commands really do
share a second.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_52__eval_scores_a_run_in_which_a_document_failed import (
    FAILED,
    _eval,
    _run,
)
from tests.scoring_example import PIPELINE

from dossier.domain.resolution import run_id

STARTED = datetime(2026, 8, 6, 14, 22, 3, 600_000, tzinfo=UTC)


class _Stopped(datetime):
    """A clock that reads `2026-08-06T14:22:03Z` whenever it is asked."""

    @classmethod
    def now(cls, tz=None):
        return STARTED


def _in_one_second(monkeypatch, *drawn: str) -> None:
    suffixes = iter(drawn)
    monkeypatch.setattr("dossier.cli.run.datetime", _Stopped)
    monkeypatch.setattr("dossier.cli.run.token_hex", lambda n: next(suffixes))


class TestRunIdsSortInTheOrderRunsStarted:
    """R0.15 — a run sharing its second with a filed run is filed after it."""

    def test_a_draw_that_sorts_first_is_moved_after(self):
        """Row 1 — the one drawing `0bbb` in the second of `4f1a`."""
        assert run_id(STARTED, "0bbb", taken=["20260806T142203Z-4f1a"]) == (
            "20260806T142203Z-4f1b"
        )

    def test_a_draw_that_already_sorts_after_stands(self):
        """Row 2 — the one drawing `9c2e`."""
        assert run_id(STARTED, "9c2e", taken=["20260806T142203Z-4f1a"]) == (
            "20260806T142203Z-9c2e"
        )

    def test_after_the_last_four_digit_suffix(self):
        """Row 3 — the one after `ffff`, which no four-digit suffix follows."""
        filed = run_id(STARTED, "0bbb", taken=["20260806T142203Z-ffff"])

        assert filed == "20260806T142203Z-ffff0"
        assert filed > "20260806T142203Z-ffff"

    def test_after_the_last_of_the_seconds_runs(self):
        """Row 7 — the one where the second already holds two runs.

        `5a5a` sorts after the first and before the last: compared with the
        first alone it would stand, and sort between them.
        """
        taken = ["20260806T142203Z-4f1a", "20260806T142203Z-7c3d"]

        assert run_id(STARTED, "5a5a", taken=taken) == "20260806T142203Z-7c3e"

    def test_a_draw_equal_to_a_filed_suffix_is_moved_after(self):
        """Row 8 — the one drawing `4f1a` in the second of `4f1a`."""
        assert run_id(STARTED, "4f1a", taken=["20260806T142203Z-4f1a"]) == (
            "20260806T142203Z-4f1b"
        )

    def test_after_a_suffix_named_by_hand(self):
        """Row 9 — the one after `mine`, which is not hex."""
        filed = run_id(STARTED, "0bbb", taken=["20260806T142203Z-mine"])

        assert filed == "20260806T142203Z-mine0"
        assert filed > "20260806T142203Z-mine"

    def test_eval_scores_the_second_of_two_runs_in_one_second(
        self, workspace: Path, monkeypatch
    ):
        """Row 4 — the one where the second run drew the smaller suffix.

        The first run fails `INC-4822` and the second answers it, so which run
        `eval` scored shows in its headline: `· 1 failed` is the first.
        """
        _in_one_second(monkeypatch, "b000", "0000")
        _run(workspace, monkeypatch, failing=FAILED)
        _run(workspace, monkeypatch, failing=None)

        first, second = sorted(path.name for path in (workspace / "runs").iterdir())
        assert first == "20260806T142203Z-b000"
        assert second == "20260806T142203Z-b001"
        headline = next(
            line
            for line in _eval(workspace, monkeypatch).output.splitlines()
            if " fields · " in line
        )
        assert re.fullmatch(r"4 documents · \d+ fields · overall \d+\.\d%", headline), headline

    def test_a_draw_in_another_second_stands(self):
        """Row 5, counter-example — the one where no run shares its second."""
        assert run_id(STARTED, "0bbb", taken=["20260907T090000Z-bbbb"]) == (
            "20260806T142203Z-0bbb"
        )

    def test_a_try_is_ordered_among_tries(self, workspace: Path, monkeypatch):
        """Row 6, counter-example — the one tried in the second of a run."""
        _in_one_second(monkeypatch, "4f1a", "0bbb")
        _run(workspace, monkeypatch, failing=None)

        tried = _cli(workspace, monkeypatch, "run", PIPELINE, "--doc", "INC-4821")

        assert tried.exit_code == 0, tried.output
        assert [path.name for path in (workspace / "tries").iterdir()] == [
            "20260806T142203Z-0bbb"
        ]
