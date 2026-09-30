"""R16.1 — after `dossier gc --apply`, every kept run that replayed before
replays as it did, and scores as it did.

The slice's acceptance rule, proved through the CLI. The other rules of spec 016
each decide part of what goes -- which runs are kept, which entries they read,
tries and replays -- and any one of them can be right while a kept run no longer
reproduces. That is the one thing `gc` must never do.

The scoring example's four incidents, run three times with the prompt edited
before each of the last two, so that each run asks afresh and the first run's
answers are its own (R5.2); then a try of `INC-4821`. Run ids made within one
second sort by their suffix, so the suffixes are pinned in increasing order and
"the latest" is the last one made (R16.2). A replay and an eval after `gc` are
asked of a `NoModelClient`: a model call there would be a finding (R4.7, R7.10).
"""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    Model,
    _edit_prompt,
    _run,
    _workspace,
)
from tests.fakes import NoModelClient
from tests.scoring_example import PIPELINE

GOLD = "gold/incidents"


def _three_runs_and_a_try(workspace: Path, monkeypatch) -> list[str]:
    """Three runs, oldest first, the prompt edited before the last two; then a try."""
    suffixes = count(1)
    monkeypatch.setattr("dossier.cli.run.token_hex", lambda n: f"{next(suffixes):04x}")
    _workspace(workspace, monkeypatch)
    runs = [_run(workspace, monkeypatch, Model())]
    for _ in range(2):
        _edit_prompt(workspace)
        runs.append(_run(workspace, monkeypatch, Model()))
    tried = _cli(workspace, monkeypatch, "run", PIPELINE, "--doc", "INC-4821")
    assert tried.exit_code == 0, tried.output
    assert len(list((workspace / "tries").iterdir())) == 1
    return runs


def _no_model(monkeypatch) -> None:
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())


def _keys(workspace: Path, run: str) -> set[str]:
    """The cache keys the run's provenance records name."""
    return {
        json.loads(record.read_text(encoding="utf-8"))["cache_key"]
        for record in (workspace / "runs" / run).rglob("*.meta.json")
    }


def _stage_entries(workspace: Path) -> set[str]:
    stage = workspace / ".dossier" / "cache" / "stage"
    return {path.name for path in stage.rglob("*") if path.is_file()}


def _files(workspace: Path) -> dict[str, bytes]:
    """Every file under `runs/`, `tries/` and `.dossier/`, by path."""
    return {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for top in ("runs", "tries", ".dossier")
        for path in (workspace / top).rglob("*")
        if path.is_file()
    }


def _gc(workspace: Path, monkeypatch):
    return _cli(workspace, monkeypatch, "gc", "--keep-last", "2", "--apply")


class TestAKeptRunReplaysAfterGc:
    """R16.1 — `gc --apply` never makes a kept run irreproducible."""

    def test_the_kept_runs_replay_and_the_oldest_is_gone(self, workspace: Path, monkeypatch):
        """Row 1 — the one where the old run and the try go, and the kept runs reproduce."""
        oldest, *kept = _three_runs_and_a_try(workspace, monkeypatch)
        only_oldest = _keys(workspace, oldest) - set().union(
            *(_keys(workspace, run) for run in kept)
        )
        assert only_oldest, "the prompt edits gave the oldest run entries of its own"
        _no_model(monkeypatch)

        collected = _gc(workspace, monkeypatch)

        assert collected.exit_code == 0, collected.output
        assert not (workspace / "runs" / oldest).exists()
        assert list((workspace / "tries").iterdir()) == []
        held = _stage_entries(workspace)
        assert not any(key in name for key in only_oldest for name in held), held
        for run in kept:
            replayed = _cli(workspace, monkeypatch, "run", "--replay", f"runs/{run}/")
            assert replayed.exit_code == 0, replayed.output
            assert "cannot be reproduced" not in replayed.output, replayed.output

    def test_the_latest_run_scores_as_it_did(self, workspace: Path, monkeypatch):
        """Row 2 — the one where `eval` prints, line for line, what it printed before."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        before = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
        assert before.exit_code == 0, before.output

        assert _gc(workspace, monkeypatch).exit_code == 0

        after = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
        assert after.exit_code == 0, after.output
        assert after.output == before.output

    def test_the_kept_runs_still_compare(self, workspace: Path, monkeypatch):
        """Row 3 — the one where the change gate still works across the runs kept."""
        _, older, latest = _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        compare = ("eval", PIPELINE, "--gold", GOLD, "--compare", older, latest)
        before = _cli(workspace, monkeypatch, *compare)
        assert before.exit_code == 0, before.output

        assert _gc(workspace, monkeypatch).exit_code == 0

        after = _cli(workspace, monkeypatch, *compare)
        assert after.exit_code == 0, after.output
        assert after.output == before.output

    def test_a_second_gc_at_once_finds_nothing(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one run again straight after."""
        _three_runs_and_a_try(workspace, monkeypatch)
        _no_model(monkeypatch)
        assert _gc(workspace, monkeypatch).exit_code == 0
        before = _files(workspace)

        again = _gc(workspace, monkeypatch)

        assert again.exit_code == 0, again.output
        assert "nothing to collect" in again.output, again.output
        assert _files(workspace) == before
