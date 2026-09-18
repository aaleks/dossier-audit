"""R2.18 — `dossier sync` names each changed item under its source line, with the
address it held and the one it holds now.

`1 changed` over a corpus of four thousand is not something a person can check.
The two addresses are the row's old and new `snapshot_path`, as full 64-character
hashes: the things a person can open and diff. A `content_hash` is never
printed, because for a source declaring `fields` it addresses a projection
nothing stored (R2.17).

Two sources. `incidents-jira` declares `fields: [key, summary]` and holds two
issues as JSON, with rendered HTML the projection excludes; `INC-4821` carries an
attachment. `incidents-manual` is the fixture folder and declares no `fields`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from tests.fakes import register_connector
from tests.pipelines import write_pipeline

from dossier.domain.ports import AttachmentRef, ItemRef, RawItem

PIPELINE = "incident-audit"
INDENT = " " * 6
ATTACHMENT = "INC-4821/report.pdf"


def issue(key: str, summary: str, rendered: str) -> bytes:
    return f'{{"key": "{key}", "summary": "{summary}", "rendered": "{rendered}"}}'.encode()


def address(payload: bytes) -> str:
    """Where the store holds these bytes: their own SHA-256, all 64 characters (R2.11)."""
    return hashlib.sha256(payload).hexdigest()


class IssueTracker:
    """Two issues at version markers it vouches for, one carrying an attachment.

    Holds what it is handed and reads it on every call, so a test can edit an
    issue or replace an attachment between two syncs.
    """

    lists_everything = False

    media_type = "application/json"

    def __init__(self) -> None:
        self.issues: dict[str, tuple[bytes, str]] = {
            "INC-4821": (issue("INC-4821", "Loss of CHF 48'200", "<p>page 3</p>"), "v37"),
            "INC-4822": (issue("INC-4822", "Batch host disk pressure", "<p>v1</p>"), "v1"),
        }
        self.attached: dict[str, tuple[bytes, str]] = {
            ATTACHMENT: (b"%PDF-1.4 report v1", "a1")
        }

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.issues):
            yield ItemRef(key=key, remote_version=self.issues[key][1], updated_at=None)

    def fetch(self, key: str) -> RawItem:
        if key in self.attached:
            payload, version = self.attached[key]
            return RawItem(
                key=key, payload=payload, media_type="application/pdf", remote_version=version
            )
        payload, version = self.issues[key]
        return RawItem(
            key=key, payload=payload, media_type=self.media_type, remote_version=version
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        for attachment, (_, version) in sorted(self.attached.items()):
            if attachment.startswith(f"{key}/"):
                yield AttachmentRef(key=attachment, item_key=key, remote_version=version)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _named(output: str, source_id: str) -> list[str]:
    """The indented lines printed under one source's count line, in order."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{source_id}  "))
    named = []
    for line in lines[start + 1 :]:
        if not line.startswith(INDENT):
            break
        named.append(line)
    return named


def _count_line(output: str, source_id: str) -> str:
    return next(line for line in output.splitlines() if line.startswith(f"{source_id}  "))


@pytest.fixture
def declared(workspace: Path, monkeypatch) -> IssueTracker:
    """Both sources declared and the pipeline naming them; nothing synced yet."""
    tracker = IssueTracker()
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: incidents-jira\n"
        "    type: issues\n"
        "    fields: [key, summary]\n"
        "  - id: incidents-manual\n"
        "    type: folder\n"
        "    path: inbox/incidents/\n",
        encoding="utf-8",
    )
    register_connector(monkeypatch, "issues", lambda config, *, workspace: tracker)
    write_pipeline(workspace, sources=["incidents-jira", "incidents-manual"])
    return tracker


@pytest.fixture
def held(workspace: Path, monkeypatch, declared: IssueTracker) -> IssueTracker:
    """Both sources synced once, so the next sync has something to compare against."""
    first = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert first.exit_code == 0, first.output
    return declared


class TestSyncNamesEachChangedItem:
    """R2.18 — each changed item is named with the address it held and the one it holds now."""

    def test_a_re_fetched_issue_is_named_with_both_addresses(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Example 1: the one where `INC-4822` moved, and the line says from what to what."""
        before, _ = held.issues["INC-4822"]
        after = issue("INC-4822", "Batch host disk pressure, root cause found", "<p>v2</p>")
        held.issues["INC-4822"] = (after, "v2")

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _named(result.output, "incidents-jira") == [
            f"{INDENT}INC-4822  {address(before)} -> {address(after)}"
        ]

    def test_the_addresses_are_snapshots_not_projections(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Example 2: the one where the source declares `fields`, and the hashes printed
        are still the ones a person can open.

        The projection's hash is what the ledger compares (R2.2); the raw payload's
        hash is what the store holds (R2.17). Only the second addresses a file.
        For the folder, which declares no `fields`, the two coincide (R2.10).
        """
        from dossier.infrastructure.ledger import Ledger

        before, _ = held.issues["INC-4822"]
        after = issue("INC-4822", "Batch host disk pressure, root cause found", "<p>v2</p>")
        held.issues["INC-4822"] = (after, "v2")
        note = workspace / "inbox" / "incidents" / "INC-4821.md"
        note_before = note.read_bytes()
        note.write_bytes(note_before + b"\nAppended after the first sync.\n")

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        with Ledger(workspace) as ledger:
            row = ledger.row("incidents-jira", "INC-4822")
        assert row is not None and row.content_hash != address(after)
        [issue_line] = _named(result.output, "incidents-jira")
        assert issue_line.endswith(f"{address(before)} -> {address(after)}")
        assert row.content_hash not in issue_line
        assert _named(result.output, "incidents-manual") == [
            f"{INDENT}INC-4821.md  {address(note_before)} -> {address(note.read_bytes())}"
        ]

    def test_a_replaced_attachment_is_named_on_its_own(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Example 3: the one where `INC-4821` did not move but its `report.pdf` did (R2.6)."""
        before, _ = held.attached[ATTACHMENT]
        after = b"%PDF-1.4 report v2, re-uploaded"
        held.attached[ATTACHMENT] = (after, "a2")

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _named(result.output, "incidents-jira") == [
            f"{INDENT}{ATTACHMENT}  {address(before)} -> {address(after)}"
        ]

    def test_an_item_re_read_to_the_same_hash_is_not_named(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Counter-example (row 4): the one where every folder file was re-read and none moved.

        Only `last_seen` moved (R2.2): `0 changed`, and nothing under the line.
        """
        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert " 0 changed " in _count_line(result.output, "incidents-manual")
        assert _named(result.output, "incidents-manual") == []
        assert _named(result.output, "incidents-jira") == []

    def test_a_first_sync_names_nothing(
        self, workspace: Path, monkeypatch, declared: IssueTracker
    ):
        """Counter-example (row 5): the one where everything is new.

        `3 new` and nothing named: a first sync of 4,000 items would print 4,000
        lines that say nothing the count does not.
        """
        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _count_line(result.output, "incidents-manual").endswith(
            "0 known · 0 changed · 3 new -> 3 fetched"
        )
        assert _named(result.output, "incidents-manual") == []
        assert _named(result.output, "incidents-jira") == []
