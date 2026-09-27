"""R11.24, at the CLI — the sync that revives `audit-note.md` names it in `changes.json`.

`audit-note.md` (the fixture spelling of `specs/_fixtures.md`'s `audit-note.pdf`)
is synced, taken out and synced away, and put back. Tracking is switched on for
the last sync only, as a person switches it on (R10.1). Before this rule, that
sync printed the note under its source line and attached two empty lists.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.fakes import FakeTracker

PIPELINE = "incident-audit"
SOURCE = "incidents-manual"
NOTE = "audit-note.md"
URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _put_back(
    workspace: Path, monkeypatch, *, payload: bytes | None = None
) -> tuple[FakeTracker, bytes]:
    """Sync, take the note away and sync, put it back and sync with tracking on."""
    import dossier.cli.main as cli

    note = workspace / "inbox" / "incidents" / NOTE
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    held = note.read_bytes()
    note.unlink()
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    note.write_bytes(held if payload is None else payload)

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    assert f"      {NOTE}  returned" in result.output
    return recorder, held


def _changes(tracker: FakeTracker) -> dict:
    [run] = tracker.runs
    return json.loads(run.artifacts["changes.json"])


class TestSyncRecordsWhatCameBack:
    """R11.24 — the record names what the lines under the source named."""

    def test_the_note_put_back_as_it_was_is_named_without_addresses(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where the record no longer says nothing happened."""
        tracker, _ = _put_back(workspace, monkeypatch)

        assert _changes(tracker) == {
            "changed": [],
            "returned": [{"source": SOURCE, "key": NOTE}],
            "tombstoned": [],
        }

    def test_the_note_put_back_amended_carries_both_addresses(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where it came back with other bytes, and is still not `changed`."""
        amended = b"# audit note, amended\n"

        tracker, held = _put_back(workspace, monkeypatch, payload=amended)

        assert _changes(tracker) == {
            "changed": [],
            "returned": [
                {
                    "source": SOURCE,
                    "key": NOTE,
                    "from": hashlib.sha256(held).hexdigest(),
                    "to": hashlib.sha256(amended).hexdigest(),
                }
            ],
            "tombstoned": [],
        }
