"""R16.5 — `dossier gc` without `--apply` deletes nothing, and prints what
`--apply` would delete and the space it would free.

The first command that deletes cannot do so by accident (decided by `a.aleks`
on 2026-09-30). The preview and `--apply` print the same counts and the same
size: the bytes of every file deleted, in MB of 10^6 bytes to one decimal.

Through the CLI, over R16.1 row 1's workspace: three runs of `incident-audit`,
the prompt edited before the last two, then a try of `INC-4821`.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R016_1__a_kept_run_replays_after_gc import (
    _files,
    _no_model,
    _three_runs_and_a_try,
)

SUMMARY = r"{verb} (\d+\.\d) MB: 1 run, 1 try, 0 replays, (\d+) cache entries"
FOOTER = "nothing deleted: run `dossier gc --apply` to delete it"


def _gc(workspace: Path, monkeypatch, *more: str):
    result = _cli(workspace, monkeypatch, "gc", *more)
    assert result.exit_code == 0, result.output
    return result.output.splitlines()


class TestGcPreviewsUnlessToldToApply:
    """R16.5 — a preview by default; `--apply` deletes what it previewed."""

    def test_a_preview_names_what_would_go_and_deletes_nothing(
        self, workspace: Path, monkeypatch
    ):
        """Row 1 — the one run without `--apply`."""
        oldest, *_ = _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        before = _files(workspace)

        lines = _gc(workspace, monkeypatch, "--keep-last", "2")

        assert re.fullmatch(SUMMARY.format(verb="would free"), lines[0]), lines
        assert lines[1] == f"  runs/{oldest}/  incident-audit, beyond the latest 2", lines
        assert lines[-1] == FOOTER, lines
        assert _files(workspace) == before

    def test_apply_deletes_what_the_preview_named(self, workspace: Path, monkeypatch):
        """Row 2 — the one with `--apply`: the same counts, the same size, and gone."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        previewed = _gc(workspace, monkeypatch, "--keep-last", "2")
        before = _files(workspace)

        applied = _gc(workspace, monkeypatch, "--keep-last", "2", "--apply")

        assert applied[0] == previewed[0].replace("would free", "freed", 1), applied
        assert applied[1] == previewed[1], applied
        assert FOOTER not in applied
        after = _files(workspace)
        freed = sum(len(data) for path, data in before.items() if path not in after)
        (megabytes, _) = re.fullmatch(SUMMARY.format(verb="freed"), applied[0]).groups()
        assert megabytes == f"{freed / 1_000_000:.1f}"

    def test_nothing_to_collect_says_so(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one with nothing left, with or without `--apply`."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        _gc(workspace, monkeypatch, "--keep-last", "2", "--apply")

        assert _gc(workspace, monkeypatch, "--keep-last", "2") == ["nothing to collect"]
        assert _gc(workspace, monkeypatch, "--keep-last", "2", "--apply") == [
            "nothing to collect"
        ]

    def test_a_megabyte_is_a_million_bytes_rounded_to_one_decimal(self):
        """Row 4: the one where 1.5 MiB is deleted.

        The workspace's files are a few kilobytes, so rows 1 and 2 print `0.0`,
        whichever unit and rounding the line used. This row is where they differ.
        """
        from dossier.domain.gc import summary_line

        line = summary_line(
            applied=False, runs=1, tries=0, replays=0, entries=0, size=1_572_864
        )

        assert line == "would free 1.6 MB: 1 run, 0 tries, 0 replays, 0 cache entries"
