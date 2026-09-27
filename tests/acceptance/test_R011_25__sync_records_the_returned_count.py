"""R11.25, at the CLI — the sync that revives `audit-note.md` records `/returned`.

`audit-note.md` (the fixture spelling of `specs/_fixtures.md`'s `audit-note.pdf`)
is synced, taken out and synced away, and put back. Tracking is switched on for
the last sync only, as a person switches it on (R10.1). Its line reads
`2 known · 0 changed · 0 new · 1 returned -> 3 fetched` (R2.25 row 1), and the
record holds the same five numbers.
"""

from __future__ import annotations

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


class TestSyncRecordsTheReturnedCount:
    """R11.25 — the numbers the line prints, `returned` among them."""

    def test_the_revived_note_is_counted_in_the_record(self, workspace: Path, monkeypatch):
        """Row 1: the one where 2 known and 1 returned account for 3 fetched."""
        import dossier.cli.main as cli

        note = workspace / "inbox" / "incidents" / NOTE
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        held = note.read_bytes()
        note.unlink()
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        note.write_bytes(held)
        recorder = FakeTracker()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert (
            f"{SOURCE}  2 known · 0 changed · 0 new · 1 returned -> 3 fetched" in result.output
        )
        [run] = recorder.runs
        assert run.metrics == {
            f"{SOURCE}/known": 2,
            f"{SOURCE}/changed": 0,
            f"{SOURCE}/new": 0,
            f"{SOURCE}/returned": 1,
            f"{SOURCE}/fetched": 3,
            f"{SOURCE}/failed": 0,
        }
