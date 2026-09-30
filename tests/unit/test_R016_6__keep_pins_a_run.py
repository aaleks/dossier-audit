"""R16.6 — `dossier gc --keep RUN` pins a run by writing `runs/<RUN>/keep`, and
refuses a run that does not exist.

A pin is on disk, not in a command: a baseline compared against weeks later
survives every later `gc` (R16.2 row 3). Pinning deletes nothing, so it is done
with or without `--apply`, before the rest of the command.

Through the CLI, over R16.1 row 1's workspace: three runs of `incident-audit`
and a try.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R016_1__a_kept_run_replays_after_gc import (
    _files,
    _no_model,
    _three_runs_and_a_try,
)

UNKNOWN = "20260101T000000Z-0000"


class TestKeepPinsARun:
    """R16.6 — `--keep RUN` writes `runs/<RUN>/keep`; an unknown run is refused."""

    def test_keep_pins_the_run_and_the_preview_keeps_it(self, workspace: Path, monkeypatch):
        """Row 1 — the one pinning the oldest of three, beyond the latest two."""
        oldest, *_ = _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)

        result = _cli(workspace, monkeypatch, "gc", "--keep", oldest, "--keep-last", "2")

        assert result.exit_code == 0, result.output
        assert (workspace / "runs" / oldest / "keep").is_file()
        assert result.output.splitlines()[0].endswith(
            ": 0 runs, 1 try, 0 replays, 0 cache entries"
        ), result.output
        assert oldest not in result.output

    def test_the_pin_outlasts_the_command(self, workspace: Path, monkeypatch):
        """Row 2 — the one where a later `gc --apply` names no `--keep`."""
        oldest, *_ = _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        assert _cli(workspace, monkeypatch, "gc", "--keep", oldest).exit_code == 0

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "2", "--apply")

        assert result.exit_code == 0, result.output
        assert (workspace / "runs" / oldest / "manifest.json").is_file()

    def test_a_run_that_does_not_exist_is_refused(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one naming a run no directory holds."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        before = _files(workspace)

        result = _cli(
            workspace, monkeypatch, "gc", "--keep", UNKNOWN, "--keep-last", "2", "--apply"
        )

        assert result.exit_code == 2, result.output
        assert (
            f"no run {UNKNOWN} -- expected runs/{UNKNOWN}/manifest.json"
            in result.stderr.splitlines()
        ), result.stderr
        assert _files(workspace) == before
