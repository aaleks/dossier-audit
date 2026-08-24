"""R2.14 — a second sync with nothing changed writes zero snapshots.

Holds for every source, whatever it can tell us about its own versions. This is
the half of the old R2.5 that survives universally -- the fetch-count half became
R2.15, which needs a source that carries a version marker and so cannot be proved
by a folder.

This was the first outer loop, and it closed with the sync slice. No single
component could satisfy it: the
connector must list and read, the domain must hash and classify, the store must
refuse to rewrite, the ledger must remember, and the CLI must report. The second
run's numbers are only zero if all five agree.
"""

from __future__ import annotations

from pathlib import Path


def _run_sync(workspace: Path, monkeypatch):
    """Invoke `dossier sync incident-audit` with the workspace as the cwd.

    The pipeline name is the argument, not a config path (R2.12): a pipeline
    declares both its `sources` and its `reference` sources, and both have to be
    held. Commands operate on the current working directory as the workspace
    root (R0.8), which is why this chdirs rather than passing a path.
    """
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    result = CliRunner().invoke(app, ["sync", "incident-audit"])
    assert result.exit_code == 0, result.output
    return result


def _store_state(workspace: Path) -> dict[str, tuple[bytes, int]]:
    """Every snapshot's content *and* modification time.

    Content alone would not catch a store that rewrote a file with identical
    bytes, which is still a write to a stored snapshot and still breaks R0.2.
    """
    store = workspace / ".dossier" / "snapshots"
    return {
        path.relative_to(store).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(store.rglob("*"))
        if path.is_file()
    }


def _ledger_content(workspace: Path) -> list[tuple]:
    """The ledger minus the columns that record *when* rather than *what*."""
    from dossier.infrastructure.ledger import Ledger

    with Ledger(workspace) as ledger:
        return [row.content() for row in ledger.rows("incidents-manual")]


class TestSecondSyncWritesNothing:
    """R2.14 — re-reading is cheap; re-storing is not."""

    def test_the_summary_reports_no_new_snapshots(self, workspace: Path, monkeypatch):
        """Example 1: the one where nothing changed, so nothing was stored."""
        _run_sync(workspace, monkeypatch)
        second = _run_sync(workspace, monkeypatch)

        assert "0 new snapshots" in second.output
        assert "0 tombstoned" in second.output
        assert "incidents-manual" in second.output, (
            "a source that did nothing is still listed (R2.13) -- a silent source "
            "is indistinguishable from a skipped one"
        )

    def test_the_store_is_untouched(self, workspace: Path, monkeypatch):
        """Example 2: the one asserted on modification times as well as content."""
        _run_sync(workspace, monkeypatch)
        after_first = _store_state(workspace)

        _run_sync(workspace, monkeypatch)

        assert _store_state(workspace) == after_first

    def test_the_ledger_content_is_unchanged(self, workspace: Path, monkeypatch):
        """Example 3: the one where only `last_seen` may have moved (R2.9)."""
        _run_sync(workspace, monkeypatch)
        after_first = _ledger_content(workspace)

        _run_sync(workspace, monkeypatch)

        assert _ledger_content(workspace) == after_first

    def test_one_edited_document_writes_one_snapshot(self, workspace: Path, monkeypatch):
        """Example 4: the one that stops a stub reporting zero unconditionally.

        Without this row the rule is satisfied by a sync that never writes
        anything at all, which would pass the three tests above and be useless.
        """
        _run_sync(workspace, monkeypatch)
        before = _store_state(workspace)

        changed = workspace / "inbox" / "incidents" / "INC-4822.md"
        changed.write_text(
            changed.read_text(encoding="utf-8") + "\nReopened 2026-08-07.\n",
            encoding="utf-8",
        )

        second = _run_sync(workspace, monkeypatch)
        after = _store_state(workspace)

        assert "1 new snapshots" in second.output
        assert len(after) == len(before) + 1
        assert before.items() <= after.items(), "the earlier snapshots must survive (R0.2)"

    def test_the_payloads_read_are_not_constrained_here(self, workspace: Path, monkeypatch):
        """Counter-example (row 5): the one where reading is expected.

        A folder source has no version marker (R1.5), so it must read every file
        to know whether it changed. The run says so plainly rather than reporting
        `0 fetched`, and that honesty is the whole reason R2.5 was split.
        """
        _run_sync(workspace, monkeypatch)
        second = _run_sync(workspace, monkeypatch)

        assert "3 fetched" in second.output
        assert "0 new snapshots" in second.output
