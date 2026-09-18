"""R11.6 — a `dossier sync` attaches `changes.json`, naming what the terminal named.

The unit test beside this one proves the record. This proves the command
attaches it -- the gap R11.4 was found to have, where a pure mapping was proved
and nothing showed the command ever called the tracker.

The fixture folder, synced once with tracking off; then `INC-4821.md` is edited
and the second sync is the run under test. Tracking is switched on in the
environment, as a person switches it on (R10.1).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from tests.fakes import FakeTracker

PIPELINE = "incident-audit"
SOURCE = "incidents-manual"
URI = "http://localhost:5000"


def _run(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    result = _run(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    return workspace


@pytest.fixture
def tracker(synced: Path, monkeypatch) -> FakeTracker:
    """Tracking switched on after the setup sync, recording to a fake that counts."""
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


class TestSyncRecordsTheChangesItNamed:
    """R11.6 — a sync attaches `changes.json`, naming what the terminal named."""

    def test_the_edited_note_is_in_the_artifact_with_both_addresses(
        self, synced: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where `INC-4821.md` moved, and the run says from what to what."""
        note = synced / "inbox" / "incidents" / "INC-4821.md"
        before = note.read_bytes()
        note.write_bytes(before + b"\nAppended after the first sync.\n")

        result = _run(synced, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        [run] = tracker.runs
        assert json.loads(run.artifacts["changes.json"]) == {
            "changed": [
                {
                    "source": SOURCE,
                    "key": "INC-4821.md",
                    "from": hashlib.sha256(before).hexdigest(),
                    "to": hashlib.sha256(note.read_bytes()).hexdigest(),
                }
            ],
            "tombstoned": [],
        }

    def test_a_sync_where_nothing_changed_still_attaches_it(
        self, synced: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where nothing moved -- two empty lists, not a missing file."""
        result = _run(synced, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        [run] = tracker.runs
        assert json.loads(run.artifacts["changes.json"]) == {"changed": [], "tombstoned": []}

    def test_a_plan_records_nothing(self, synced: Path, monkeypatch, tracker: FakeTracker):
        """Counter-example (row 3): the one where `--plan` follows the sync.

        No MLflow run, so nothing attached (R11.1 row 5): the record belongs to
        the command that fetched.
        """
        result = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert tracker.runs == []
