"""R20.1 — a command that writes the workspace holds its lock, and a second one
is refused at once, naming the first.

Spec 015's flow is a daily cron job, and nothing stopped two commands writing
one workspace at once: `gc --apply` beside a `run` deleted what the run was
writing, and two syncs wrote one ledger. The lock is the operating system's own,
so the holder here is a real `WorkspaceLock` -- in this process for the rows
that need the command beside it, and in a process of its own for the row where
that process is killed. Holding it in-process is a real second writer on both
systems: Windows refuses a second handle in the same process, and `flock`
refuses a second open of the file.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    Model,
    _workspace,
)
from tests.acceptance.test_R016_1__a_kept_run_replays_after_gc import _files
from tests.fakes import register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

SINCE = datetime(2026, 10, 2, 7, 30, 12, tzinfo=UTC)
HELD = (
    "another dossier command is writing this workspace: run, pid 4120, "
    "since 2026-10-02T07:30:12Z. Try again when it has finished"
)
UNNAMED = "another dossier command is writing this workspace. Try again when it has finished"

# The spec's left-hand column: every command that writes, a try and a replay
# included. Each is refused before it reads anything, so none of them needs a
# workspace it could have run in.
WRITERS = {
    "sync": ("sync", PIPELINE),
    "convert": ("convert", PIPELINE),
    "run": ("run", PIPELINE),
    "a try": ("run", PIPELINE, "--doc", "INC-4821"),
    "a replay": ("run", "--replay", "runs/20261002T073012Z-a3f9c1"),
    "embed": ("embed", "incidents"),
    "gc --apply": ("gc", "--apply"),
    "review apply": (
        "review",
        "apply",
        PIPELINE,
        "--gold",
        "gold/incidents",
        "--verified-by",
        "a.aleks",
    ),
}
# The right-hand column's three that row 3 names.
READERS = {
    "status": ("status",),
    "run --plan": ("run", PIPELINE, "--plan"),
    "gc without --apply": ("gc",),
}

# A writer in a process of its own, killed while it holds the lock (row 4).
HOLDER = """
import sys, time
from datetime import UTC, datetime
from pathlib import Path

from dossier.infrastructure.lock import WorkspaceLock

since = datetime(2026, 10, 2, 7, 30, 12, tzinfo=UTC)
with WorkspaceLock(Path(sys.argv[1]), command="run", pid=4120, since=since):
    print("held", flush=True)
    time.sleep(300)
"""


def _holding(workspace: Path):
    """`dossier run incident-audit`, pid 4120, holding the workspace since 07:30:12."""
    from dossier.infrastructure.lock import WorkspaceLock

    return WorkspaceLock(workspace, command="run", pid=4120, since=SINCE)


def _syncable(workspace: Path, monkeypatch) -> list[str]:
    """A workspace a sync would fill; the sources the connector was built for."""
    built: list[str] = []
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])

    def connector(config, *, workspace):
        built.append(config.id)
        return IssueTracker(ISSUES)

    register_connector(monkeypatch, SOURCE_TYPE, connector)
    return built


def _model(monkeypatch) -> None:
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())


class TestASecondWriterIsRefused:
    """R20.1 — one writer at a time, and a second is told who and since when."""

    def test_a_sync_beside_a_run_is_refused_naming_it(self, workspace: Path, monkeypatch):
        """Row 1 — the one where a sync starts while a run writes the workspace."""
        built = _syncable(workspace, monkeypatch)

        with _holding(workspace):
            result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 2, result.output
        assert result.stderr.splitlines() == [HELD]
        assert built == [], "refused before anything is read: no connector built"
        assert not (workspace / ".dossier" / "ledger.db").exists()
        assert not (workspace / ".dossier" / "snapshots").exists()

    @pytest.mark.parametrize("command", WRITERS.values(), ids=WRITERS.keys())
    def test_every_command_that_writes_is_refused(
        self, workspace: Path, monkeypatch, command: tuple[str, ...]
    ):
        """Row 1, across the spec's table — the one where each writer starts beside the run."""
        with _holding(workspace):
            result = _cli(workspace, monkeypatch, *command)

        assert result.exit_code == 2, result.output
        assert result.stderr.splitlines() == [HELD]

    def test_a_gc_beside_a_run_deletes_nothing(self, workspace: Path, monkeypatch):
        """Row 2 — the one where `gc --apply` starts while a run writes the workspace."""
        _workspace(workspace, monkeypatch)
        _model(monkeypatch)
        tried = _cli(workspace, monkeypatch, "run", PIPELINE, "--doc", "INC-4821")
        assert tried.exit_code == 0, tried.output

        with _holding(workspace):
            before = _files(workspace)
            result = _cli(workspace, monkeypatch, "gc", "--apply")
            after = _files(workspace)

        assert result.exit_code == 2, result.output
        assert result.stderr.splitlines() == [HELD]
        assert after == before
        # The try was there to delete: once the run lets go, gc deletes it.
        collected = _cli(workspace, monkeypatch, "gc", "--apply")
        assert collected.exit_code == 0, collected.output
        assert list((workspace / "tries").iterdir()) == []

    @pytest.mark.parametrize("command", READERS.values(), ids=READERS.keys())
    def test_a_command_that_writes_nothing_runs_beside_it(
        self, workspace: Path, monkeypatch, command: tuple[str, ...]
    ):
        """Row 3, counter-example — the one where status, a plan or a gc preview is asked."""
        _workspace(workspace, monkeypatch)

        with _holding(workspace):
            result = _cli(workspace, monkeypatch, *command)

        assert result.exit_code == 0, result.output
        assert HELD not in result.output

    def test_a_killed_writer_leaves_no_lock(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one where the run is killed and its process gone."""
        _syncable(workspace, monkeypatch)
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(workspace)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            line = holder.stdout.readline().strip()
            assert line == "held", holder.stderr.read()
            refused = _cli(workspace, monkeypatch, "sync", PIPELINE)
            assert (refused.exit_code, refused.stderr.splitlines()) == (2, [HELD])
        finally:
            holder.kill()
            holder.communicate()

        synced = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert synced.exit_code == 0, synced.output

    def test_one_writer_after_another_both_run(self, workspace: Path, monkeypatch):
        """Row 5, counter-example — the one where a sync, then a run, each ends first."""
        _syncable(workspace, monkeypatch)
        _model(monkeypatch)

        synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
        ran = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert synced.exit_code == 0, synced.output
        assert ran.exit_code == 0, ran.output

    def test_a_writer_that_failed_lets_go_too(self, workspace: Path, monkeypatch):
        """Row 5, counter-example — the one where the first command ends in an error."""
        _syncable(workspace, monkeypatch)

        failed = _cli(workspace, monkeypatch, "sync", "no-such-pipeline")
        synced = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert failed.exit_code == 2, failed.output
        assert HELD not in failed.output
        assert synced.exit_code == 0, synced.output

    @pytest.mark.parametrize(
        "details",
        [None, '{"command": "run", "pid": 41', "[]", '{"command": "run", "pid": "4120"}'],
        ids=["missing", "cut off", "not an object", "not the details a writer leaves"],
    )
    def test_a_holder_not_yet_named_is_refused_without_details(
        self, workspace: Path, monkeypatch, details: str | None
    ):
        """Row 6 — the one where the lock is held and `lock.json` does not say by whom."""
        built = _syncable(workspace, monkeypatch)

        with _holding(workspace):
            named = workspace / ".dossier" / "lock.json"
            if details is None:
                named.unlink()
            else:
                named.write_bytes(details.encode("utf-8"))
            result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 2, result.output
        assert result.stderr.splitlines() == [UNNAMED]
        assert built == []
