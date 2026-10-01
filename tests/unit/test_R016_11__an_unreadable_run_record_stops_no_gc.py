"""R16.11 — a run whose `manifest.json` or `failures.json` cannot be read stops
no `gc`.

Neither file is written all at once (R4.27), so a run killed while writing one
leaves it cut short. A manifest that cannot be read says nothing of the run:
the directory is left as one with no manifest is (R16.2 row 6), and named. A
`failures.json` that cannot be read is a replay that stops before its stages,
R16.8's case.

Through the CLI, over R16.8's two runs, each file cut to its first character.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.unit.test_R016_7__an_unreplayable_kept_run_does_not_stop_gc import KEPT_AS_IT_IS
from tests.unit.test_R016_8__a_run_that_stops_before_its_stages_keeps_every_entry import (
    NOT_TRACED,
    _held,
    _stage_keys,
    _two_runs,
)

LEFT = "  left as it is: runs/{run}/manifest.json cannot be read: "


def _cut_short(path: Path) -> None:
    path.write_bytes(path.read_bytes()[:1])


class TestAnUnreadableRunRecordStopsNoGc:
    """R16.11 — named, and `gc` goes on."""

    def test_a_manifest_cut_short_leaves_its_directory(self, workspace: Path, monkeypatch):
        """Row 1 — the one killed while its manifest was written."""
        older, latest = _two_runs(workspace, monkeypatch)
        _cut_short(workspace / "runs" / older / "manifest.json")

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        (named,) = [line for line in result.stderr.splitlines() if "left as it is" in line]
        assert named.startswith(LEFT.format(run=older)), named
        assert (workspace / "runs" / older / "manifest.json").is_file()
        assert (workspace / "runs" / latest / "manifest.json").is_file()

    def test_a_failures_record_cut_short_keeps_every_entry(self, workspace: Path, monkeypatch):
        """Row 2 — the one killed while it recorded what failed."""
        _, latest = _two_runs(workspace, monkeypatch)
        read = _stage_keys(workspace)
        _cut_short(workspace / "runs" / latest / "failures.json")

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        errors = result.stderr.splitlines()
        named = errors.index(NOT_TRACED.format(run=latest))
        reason = KEPT_AS_IT_IS.format(run=latest) + "failures.json cannot be read: "
        assert errors[named - 1].startswith(reason), errors
        assert all(_held(workspace, key) for key in read)

    def test_readable_records_are_not_named(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one where both files are whole."""
        _two_runs(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        assert "left as it is" not in result.stderr
        assert "cannot be read" not in result.stderr
