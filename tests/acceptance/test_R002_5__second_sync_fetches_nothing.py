"""R002.5 — a second sync with nothing changed fetches nothing and writes nothing.

THE OPEN OUTER LOOP. This test is red on purpose and is excluded from the default
suite by the `outer_loop` marker. It closes when the first vertical slice lands;
at that point the marker comes off, the test joins the default run, and the rule's
status in `specs/002-ledger-and-sync.md` moves from IN PROGRESS to MET.

Run it deliberately:

    pytest -m outer_loop

Why this rule first. It is the smallest claim that cannot be satisfied by any one
component: it needs the folder connector to list, the store to write a
content-addressed snapshot, the ledger to remember a hash, and the CLI to report
what it did. Each inner `/tdd` cycle drives one of those, and none of them can be
faked past this test -- the second run's numbers are only zero if all four
genuinely agree with each other.

It is also the promise a reader of the design deck would check first: "tomorrow's
420 issues cost 20 downloads, not 420."
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.outer_loop


def _run_sync(workspace: Path, monkeypatch):
    """Invoke `dossier sync incident-audit` with the workspace as the cwd.

    The pipeline name is the argument, not a config path (R2.12): a pipeline
    declares both its `sources` and its `reference` sources, and both have to be
    held. Commands operate on the current working directory as the workspace
    root (R0.8), which is why this chdirs rather than passing a path.

    Imported inside the helper rather than at module scope so that collecting the
    default suite does not fail on a package that does not exist yet. Until the
    slice lands this raises ModuleNotFoundError, which is the correct red: nothing
    implements it, rather than something implementing it wrongly.
    """
    from dossier.cli.main import app
    from typer.testing import CliRunner

    monkeypatch.chdir(workspace)
    result = CliRunner().invoke(app, ["sync", "incident-audit"])
    assert result.exit_code == 0, result.output
    return result


def _snapshot_bytes(workspace: Path) -> dict[str, bytes]:
    store = workspace / ".dossier" / "snapshots"
    return {
        path.relative_to(store).as_posix(): path.read_bytes()
        for path in sorted(store.rglob("*"))
        if path.is_file()
    }


class TestSecondSyncIsFree:
    """R2.5 — the observable promise of incremental sync."""

    def test_second_sync_reports_no_work(self, workspace: Path, monkeypatch):
        """The one where nothing changed, so nothing should happen.

        Example 1: three fixture documents, synced twice, unchanged in between.
        """
        _run_sync(workspace, monkeypatch)
        second = _run_sync(workspace, monkeypatch)

        assert "0 fetched" in second.output
        assert "0 new snapshots" in second.output
        assert "0 tombstoned" in second.output
        assert "incidents-manual" in second.output, (
            "a source that did nothing is still listed (R2.13) -- a silent source "
            "is indistinguishable from a skipped one"
        )

    def test_second_sync_writes_no_snapshot(self, workspace: Path, monkeypatch):
        """Example 2: the store is byte-identical after the second run.

        Asserted over content rather than over a count, because a store that
        rewrote a file with identical bytes would still violate R0.2.
        """
        _run_sync(workspace, monkeypatch)
        after_first = _snapshot_bytes(workspace)

        _run_sync(workspace, monkeypatch)
        assert _snapshot_bytes(workspace) == after_first

    def test_a_changed_document_is_the_only_one_refetched(
        self, workspace: Path, monkeypatch
    ):
        """Example 4 (counter-example): the rule stops applying for one document.

        The counter-example is the half that matters. A sync that reported "0
        fetched" unconditionally would pass the two tests above and be useless.
        """
        _run_sync(workspace, monkeypatch)

        changed = workspace / "inbox" / "incidents" / "INC-4822.md"
        changed.write_text(
            changed.read_text(encoding="utf-8") + "\nReopened 2026-08-07.\n",
            encoding="utf-8",
        )

        second = _run_sync(workspace, monkeypatch)
        assert "1 fetched" in second.output
        assert "1 new snapshot" in second.output
