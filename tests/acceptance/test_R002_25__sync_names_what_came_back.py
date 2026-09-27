"""R2.25, at the CLI — `dossier sync` counts and names what came back.

`audit-note.md` (the fixture spelling of `specs/_fixtures.md`'s `audit-note.pdf`)
is taken out of the folder, synced away, and put back. The sync that finds it
printed `2 known · 0 changed · 0 new -> 3 fetched`: three fetched, and two
accounted for. Playground exercise 04 found it.
"""

from __future__ import annotations

import re
from pathlib import Path

PIPELINE = "incident-audit"
SOURCE = "incidents-manual"
INDENT = " " * 6
NOTE = "audit-note.md"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _source_line(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith(f"{SOURCE}  "))


def _gone_and_back(workspace: Path, monkeypatch, *, payload: bytes | None = None) -> str:
    """Sync, take the note away and sync, put it back and sync; the last output."""
    note = workspace / "inbox" / "incidents" / NOTE
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    held = note.read_bytes()
    note.unlink()
    assert "tombstoned" in _cli(workspace, monkeypatch, "sync", PIPELINE).output
    note.write_bytes(held if payload is None else payload)

    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    return result.output


class TestSyncNamesWhatCameBack:
    """R2.25 — returned, counted and named under its source."""

    def test_a_note_put_back_is_counted_and_named_as_returned(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where three fetched add up to three."""
        output = _gone_and_back(workspace, monkeypatch)

        assert _source_line(output) == (
            f"{SOURCE}  2 known · 0 changed · 0 new · 1 returned -> 3 fetched"
        )
        assert f"{INDENT}{NOTE}  returned" in output.splitlines()

    def test_a_note_put_back_changed_names_both_addresses(self, workspace: Path, monkeypatch):
        """Row 2: the one where it came back with other bytes.

        Returned and not changed, with the address it held and the one it holds
        now, each the full 64 characters, as R2.18 prints them.
        """
        output = _gone_and_back(workspace, monkeypatch, payload=b"# audit note, amended\n")

        assert " 0 changed · 0 new · 1 returned -> " in _source_line(output)
        named = [line for line in output.splitlines() if line.startswith(f"{INDENT}{NOTE}  ")]
        assert len(named) == 1
        assert re.fullmatch(
            rf"{INDENT}{re.escape(NOTE)}  returned  [0-9a-f]{{64}} -> [0-9a-f]{{64}}", named[0]
        ), named[0]

    def test_a_sync_where_nothing_came_back_reads_as_it_always_did(
        self, workspace: Path, monkeypatch
    ):
        """Counter-example (row 4): the one with no `returned` term."""
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        output = _cli(workspace, monkeypatch, "sync", PIPELINE).output

        assert "returned" not in output
        assert _source_line(output).endswith(" 0 new -> 3 fetched")
