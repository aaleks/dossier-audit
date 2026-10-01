"""R16.4 — `gc` deletes every try and every replay, under a kept run as well.

A try is never replayed or scored (R4.20), and an answer of its that a run was
served is that run's entry (R16.3 row 3). A replay is byte copies of entries its
run reproduces again at any time (R0.12). What else a kept run holds stays.

Through `gc_plan`, over a workspace the CLI made: the scoring example's four
incidents synced and run once, the run pinned with `keep` and replayed, then a
try of `INC-4821`. What `gc` would delete is listed, and nothing is deleted yet.
A replay under a run that is itself deleted goes with its run, so the plan names
replays under kept runs alone.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.unit.test_R016_3__an_entry_a_kept_run_reads_is_never_deleted import (
    _plan,
    _run,
    _workspace,
)


def _held(workspace: Path, monkeypatch) -> tuple[str, str, str]:
    """A run pinned and replayed, and a try; their ids."""
    _workspace(workspace, monkeypatch)
    run = _run(workspace, monkeypatch)
    (workspace / "runs" / run / "keep").write_text("", encoding="utf-8")
    replayed = _cli(workspace, monkeypatch, "run", "--replay", f"runs/{run}/")
    assert replayed.exit_code == 0, replayed.output
    (replay,) = [path.name for path in (workspace / "runs" / run / "replays").iterdir()]
    tried = _run(workspace, monkeypatch, "--doc", "INC-4821")
    return run, replay, tried


class TestTriesAndReplaysAreDeleted:
    """R16.4 — every try, and every replay, kept run or not."""

    def test_a_try_is_deleted(self, workspace: Path, monkeypatch):
        """Row 1 — the one under `tries/`."""
        _, _, tried = _held(workspace, monkeypatch)

        assert _plan(workspace).tries == (f"tries/{tried}",)

    def test_a_replay_under_a_kept_run_is_deleted(self, workspace: Path, monkeypatch):
        """Row 2 — the one under a run pinned with `keep`."""
        run, replay, _ = _held(workspace, monkeypatch)

        plan = _plan(workspace)

        assert plan.replays == (f"runs/{run}/replays/{replay}",)
        assert plan.runs == ()

    def test_what_else_a_kept_run_holds_stays(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — its manifest, failures, pin and artifact copies."""
        run, _, _ = _held(workspace, monkeypatch)

        plan = _plan(workspace)

        named = {*plan.tries, *plan.replays, *(f"runs/{held.run_id}" for held in plan.runs)}
        for held in ("manifest.json", "failures.json", "keep", "extract/INC-4821.json"):
            path = f"runs/{run}/{held}"
            assert not any(path.startswith(name + "/") for name in named), held
            assert (workspace / path).is_file()

    def test_a_directory_not_named_as_one_is_left(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one where a person kept notes beside them."""
        run, replay, tried = _held(workspace, monkeypatch)
        (workspace / "tries" / "my-notes").mkdir()
        (workspace / "runs" / run / "replays" / "my-notes").mkdir()

        plan = _plan(workspace)

        assert plan.tries == (f"tries/{tried}",)
        assert plan.replays == (f"runs/{run}/replays/{replay}",)
