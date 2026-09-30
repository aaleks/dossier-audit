"""R16.7 — a kept run that already cannot be replayed is named, and does not
stop `gc`.

What `gc` guarantees is that a run which replayed before it replays after it
(R16.1). A kept run whose replay already stops -- an entry deleted by hand, a
run killed before it ended -- could not be reproduced before `gc` either.
Stopping would protect nothing, and a run stopped with Ctrl-C, the latest and so
kept, would block every `gc` until deleted by hand. The entries its replay read
before it stopped are kept.

Through the CLI: `extract`, `notes` and `verify` (R6.29 row 2's pipeline) over
the scoring example, run twice. The latest is then made a run killed during
`verify`: its `verify` entry for `INC-4822` is gone, and a killed run writes no
`failures.json` (R4.27 row 5).
"""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    AFTER,
    Model,
    _workspace,
)
from tests.fakes import NoModelClient
from tests.scoring_example import PIPELINE

KEPT_AS_IT_IS = "  kept as it is: runs/{run}/ cannot be replayed: "


def _key(workspace: Path, run: str, step: str, document: str) -> str:
    record = workspace / "runs" / run / step / f"{document}.meta.json"
    return json.loads(record.read_text(encoding="utf-8"))["cache_key"]


def _held(workspace: Path, key: str) -> bool:
    return (workspace / ".dossier" / "cache" / "stage" / key[:2] / key[2:4] / key).is_file()


def _killed_during_verify(workspace: Path, monkeypatch) -> str:
    """Two runs, the latest then as a run killed during `verify`; the latest's id."""
    import dossier.cli.bootstrap as cli

    suffixes = count(1)
    monkeypatch.setattr("dossier.cli.run.token_hex", lambda n: f"{next(suffixes):04x}")
    _workspace(workspace, monkeypatch, **AFTER)
    for _ in range(2):
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
    latest = sorted(path.name for path in (workspace / "runs").iterdir())[-1]
    lost = _key(workspace, latest, "verify", "INC-4822")
    stage = workspace / ".dossier" / "cache" / "stage" / lost[:2] / lost[2:4]
    for path in stage.glob(f"{lost}*"):
        path.unlink()
    (workspace / "runs" / latest / "failures.json").unlink()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return latest


class TestAnUnreplayableKeptRunDoesNotStopGc:
    """R16.7 — named on stderr, and `gc` goes on."""

    def test_the_run_is_named_and_gc_goes_on(self, workspace: Path, monkeypatch):
        """Row 1 — the one killed during `verify`, and kept as the latest."""
        latest = _killed_during_verify(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        (named,) = [line for line in result.stderr.splitlines() if "kept as it is" in line]
        assert named.startswith(KEPT_AS_IT_IS.format(run=latest)), named
        assert "INC-4822" in named, named
        assert result.output.splitlines()[-1].startswith("  runs/"), "gc went on and deleted"

    def test_what_its_replay_read_before_it_stopped_is_kept(self, workspace: Path, monkeypatch):
        """Row 2 — the one whose `extract` answers are kept."""
        latest = _killed_during_verify(workspace, monkeypatch)
        extracted = [
            _key(workspace, latest, "extract", key)
            for key in ("INC-4821", "INC-4822", "INC-4901", "INC-5455")
        ]

        assert _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply").exit_code == 0

        assert all(_held(workspace, key) for key in extracted)

    def test_a_run_that_replays_is_not_named(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one where every kept run replays."""
        import dossier.cli.bootstrap as cli

        suffixes = count(1)
        monkeypatch.setattr("dossier.cli.run.token_hex", lambda n: f"{next(suffixes):04x}")
        _workspace(workspace, monkeypatch, **AFTER)
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1")

        assert result.exit_code == 0, result.output
        assert "kept as it is" not in result.output + result.stderr
