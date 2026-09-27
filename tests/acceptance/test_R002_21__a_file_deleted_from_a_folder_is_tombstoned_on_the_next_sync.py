"""R2.21 — tombstones are computed against any listing that is complete.

A listing is complete for one of two reasons: sync asked for everything
(`since=None`), or the connector declares that it returns everything whatever
it is asked (`lists_everything`, R1.11). Before this rule only the first
counted, and a folder -- which returns everything on every sync -- was believed
only on its first one. A file deleted from the folder afterwards stayed `active`
for ever.

The workspace's folder source holds `INC-4821.md`, `INC-4822.md` and
`audit-note.md` (the fixture spelling of `specs/_fixtures.md`'s `audit-note.pdf`).
It is synced once, so a watermark exists and every later sync is windowed; the
deletion under test happens after that.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PIPELINE = "incident-audit"
SOURCE = "incidents-manual"
INDENT = " " * 6
NOTE = "audit-note.md"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _states(workspace: Path) -> dict[str, str]:
    from dossier.infrastructure.ledger import Ledger

    return {row.key: row.state.value for row in Ledger(workspace).rows(SOURCE)}


def _first_seen(workspace: Path, key: str):
    from dossier.infrastructure.ledger import Ledger

    return next(row.first_seen for row in Ledger(workspace).rows(SOURCE) if row.key == key)


def _under_source(output: str) -> list[str]:
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{SOURCE}  "))
    under = []
    for line in lines[start + 1 :]:
        if not line.startswith(INDENT):
            break
        under.append(line)
    return under


def _summary(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith("ledger updated"))


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """The folder synced once: a watermark exists, so the next listing is windowed."""
    first = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert first.exit_code == 0, first.output
    assert _states(workspace) == {
        "INC-4821.md": "active",
        "INC-4822.md": "active",
        NOTE: "active",
    }
    return workspace


class TestAFileDeletedFromAFolderIsTombstonedOnTheNextSync:
    """R2.21 — a complete listing is subtracted from, whichever way it is complete."""

    def test_the_deleted_note_is_tombstoned_and_named(self, synced: Path, monkeypatch):
        """Example 1: the one where the folder loses a file after the first sync.

        The watermark is set, so sync did not ask for everything -- but the
        folder returned everything anyway, and says so (R1.11).
        """
        (synced / "inbox" / "incidents" / NOTE).unlink()

        result = _cli(synced, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _states(synced)[NOTE] == "tombstoned"
        assert _under_source(result.output) == [f"{INDENT}{NOTE}  tombstoned"]
        assert "1 tombstoned" in _summary(result.output)

    def test_the_rest_of_the_folder_is_untouched(self, synced: Path, monkeypatch):
        """Example 1, the other half: only what left is subtracted.

        A subtraction that took more than the missing file would be the failure
        R2.7 row 4 exists to prevent, so the two remaining rows stay `active`.
        """
        (synced / "inbox" / "incidents" / NOTE).unlink()

        result = _cli(synced, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _states(synced) == {
            "INC-4821.md": "active",
            "INC-4822.md": "active",
            NOTE: "tombstoned",
        }

    def test_a_restored_note_goes_back_to_active_with_its_first_seen_kept(
        self, synced: Path, monkeypatch
    ):
        """Example 3: the one where the file comes back.

        R2.7 row 3 -- reachable for a folder for the first time, because before
        this rule a folder never tombstoned anything after its first sync.
        """
        note = synced / "inbox" / "incidents" / NOTE
        first_seen = _first_seen(synced, NOTE)
        content = note.read_bytes()
        note.unlink()
        gone = _cli(synced, monkeypatch, "sync", PIPELINE)
        assert gone.exit_code == 0, gone.output
        assert _states(synced)[NOTE] == "tombstoned"

        note.write_bytes(content)
        result = _cli(synced, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _states(synced)[NOTE] == "active"
        assert _first_seen(synced, NOTE) == first_seen
        # Named once, as what happened to it (R2.25).
        assert _under_source(result.output) == [f"{INDENT}{NOTE}  returned"]
