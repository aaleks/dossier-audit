"""R16.10 — a run directory is deleted with its `manifest.json` last, so an
interrupted `--apply` leaves a run the next `gc` deletes.

A directory under `runs/` is a run while it holds `manifest.json` (R16.2).
Deleted manifest first, or in whatever order the file system lists it, a `gc`
stopped part way leaves a directory no later `gc` counts as a run or deletes.

Through the CLI, over R16.8's two runs: `--keep-last 1` deletes the older.
Every file is removed through `os.unlink`, which the test watches, and stops.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.unit.test_R016_8__a_run_that_stops_before_its_stages_keeps_every_entry import (
    _two_runs,
)


class _Stopped(Exception):
    """Ctrl-C, or anything else that ends `gc` between two deletions."""


def _watch_deletions(monkeypatch, *, stop_after: int | None = None) -> list[Path]:
    """Every file deleted from now, in order; stopped after `stop_after` of them."""
    deleted: list[Path] = []
    unlink = os.unlink

    def watched(path, *args, **kwargs):
        if stop_after is not None and len(deleted) == stop_after:
            raise _Stopped(path)
        unlink(path, *args, **kwargs)
        deleted.append(Path(path))

    monkeypatch.setattr(os, "unlink", watched)
    return deleted


class TestAnInterruptedApplyIsFinishedByTheNext:
    """R16.10 — the manifest goes last, so a stopped run is still a run."""

    def test_the_manifest_is_the_last_file_of_the_run_deleted(
        self, workspace: Path, monkeypatch
    ):
        """Row 1 — the one stopped part way, at whichever file: the manifest is still there.

        Watched rather than stopped at one point: the manifest going last is
        what makes every stopping point leave it.
        """
        older, _ = _two_runs(workspace, monkeypatch)
        run = workspace / "runs" / older
        # Listed after `manifest.json` by name, as a file system may list it.
        (run / "review.md").write_text("Checked INC-4821 by hand.\n", encoding="utf-8")
        files = sorted(path for path in run.rglob("*") if path.is_file())
        deleted = _watch_deletions(monkeypatch)

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        own = [path for path in deleted if run in path.parents]
        assert sorted(own) == files
        assert own[-1] == run / "manifest.json", [path.name for path in own]

    def test_the_next_gc_finishes_the_job(self, workspace: Path, monkeypatch):
        """Row 2 — the one stopped after the first file, then run again."""
        older, _ = _two_runs(workspace, monkeypatch)
        _watch_deletions(monkeypatch, stop_after=1)

        stopped = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert isinstance(stopped.exception, _Stopped), stopped.output
        assert (workspace / "runs" / older / "manifest.json").is_file()
        monkeypatch.setattr(os, "unlink", _UNLINK)

        again = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert again.exit_code == 0, again.output
        summary = again.stdout.splitlines()[0]
        assert summary.startswith("freed ") and ": 1 run, " in summary, again.output
        assert not (workspace / "runs" / older).exists()

    def test_an_apply_not_stopped_leaves_nothing_of_the_run(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one that ran to the end."""
        older, _ = _two_runs(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        assert not (workspace / "runs" / older).exists()


_UNLINK = os.unlink
