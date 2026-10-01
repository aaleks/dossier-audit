"""R16.9 — `--keep-last` below 1 is refused before anything is read or deleted.

Every other command reads a pipeline's latest run: `eval` scores it, `status`
names it, and `embed` carries its answers (R18.8). `--keep-last 0` would delete
it, and every run beside it that is not pinned, with one typo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
from tests.unit.test_R016_8__a_run_that_stops_before_its_stages_keeps_every_entry import (
    _two_runs,
)


def _files(workspace: Path) -> dict[str, bytes]:
    return {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


class TestKeepLastBelowOneIsRefused:
    """R16.9 — exit 2, and not a byte changes."""

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("0", id="row 1: the one where a typo would delete the latest run"),
            pytest.param("-1", id="row 2: the one where a negative is not keep-none either"),
        ],
    )
    def test_the_value_is_refused_and_nothing_changes(
        self, workspace: Path, monkeypatch, value: str
    ):
        _two_runs(workspace, monkeypatch)
        before = _files(workspace)

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", value, "--apply")

        assert result.exit_code == 2, result.output
        assert "--keep-last" in result.output, result.output
        assert "x>=1" in result.output, result.output
        assert _files(workspace) == before

    def test_one_keeps_the_latest(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one where 1 is the least that is kept."""
        older, latest = _two_runs(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        assert not (workspace / "runs" / older).exists()
        assert (workspace / "runs" / latest / "manifest.json").is_file()
