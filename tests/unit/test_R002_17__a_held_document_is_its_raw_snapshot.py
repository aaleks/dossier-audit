"""R2.17 — a held document is the raw payload its ledger row's `snapshot_path` addresses.

Normalisation decides whether an item changed; it never decides which bytes are
held. For a source that declares no `fields` the normalised hash and the raw
payload's own hash coincide (R2.10), which is why reading a document by its
`content_hash` looked correct until a source declared `fields`.

`incidents-jira` declares `fields: [key, summary]` and holds `INC-4821` as a JSON
issue whose rendered HTML the projection excludes. The tracker reports it as
`text/markdown`, so the shipped passthrough converter can read it: which
converter reads a document is not what this rule is about, only which bytes it
is handed. The fixture folder `incidents-manual`, declaring no `fields`, is the
counter-example beside it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from tests.fakes import register_connector
from tests.pipelines import write_pipeline

from dossier.application.plan import pinned_documents
from dossier.domain.ledger import LedgerRow
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.infrastructure.ledger import Ledger

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
SNAPSHOTS = Path(".dossier") / "snapshots"


def issue(rendered: str) -> bytes:
    """`INC-4821` as the tracker sends it, rendered HTML and all."""
    return (
        f'{{"key": "INC-4821", "summary": "Loss of CHF 48\'200", "rendered": "{rendered}"}}'
    ).encode()


RAW = issue("<p>Loss of CHF 48'200</p>")


class IssueTracker:
    """One issue, at a version marker it vouches for."""

    media_type = "text/markdown"

    def __init__(self) -> None:
        self.payload, self.version = RAW, "v37"

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        yield ItemRef(key="INC-4821", remote_version=self.version, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        return RawItem(
            key=key,
            payload=self.payload,
            media_type=self.media_type,
            remote_version=self.version,
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _rows(workspace: Path, source_id: str) -> list[LedgerRow]:
    with Ledger(workspace) as ledger:
        return ledger.rows(source_id)


def _snapshot_files(workspace: Path) -> list[Path]:
    return sorted(path for path in (workspace / SNAPSHOTS).rglob("*") if path.is_file())


@pytest.fixture
def tracker(workspace: Path, monkeypatch) -> IssueTracker:
    """The tracker declaring `fields`, and the fixture folder declaring none, synced once."""
    issues = IssueTracker()
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
    register_connector(monkeypatch, "issues", lambda config, *, workspace: issues)
    write_pipeline(workspace, sources=["incidents-jira", "incidents-manual"])

    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    return issues


class TestAHeldDocumentIsItsRawSnapshot:
    """R2.17 — a held document is the raw payload its row's `snapshot_path` addresses."""

    def test_the_row_addresses_the_payload_as_fetched(self, workspace: Path, tracker):
        """Example 1: the one where `INC-4821` is synced from a source declaring `fields`.

        The file exists at the row's `snapshot_path`, holds the payload as the
        tracker sent it, and its SHA-256 is the path's last segment.
        """
        (row,) = _rows(workspace, "incidents-jira")
        snapshot = workspace / SNAPSHOTS / row.snapshot_path

        assert snapshot.read_bytes() == RAW
        assert hashlib.sha256(RAW).hexdigest() == Path(row.snapshot_path).name

    def test_resolution_pins_the_raw_address(self, workspace: Path, tracker):
        """Example 2: the one where `incident-audit` is resolved after that sync.

        Pinned by the address the row's `snapshot_path` gives, not by its
        `content_hash`: the manifest names bytes that exist (spec 004).
        """
        (row,) = _rows(workspace, "incidents-jira")

        assert pinned_documents([row]) == {"INC-4821": hashlib.sha256(RAW).hexdigest()}
        assert row.content_hash != hashlib.sha256(RAW).hexdigest(), "the hashes differ"

    def test_conversion_reads_the_payload_byte_for_byte(
        self, workspace: Path, monkeypatch, tracker
    ):
        """Example 3: the one where `INC-4821` is converted."""
        result = _cli(workspace, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "incidents-jira  1 held · 1 converted · 0 cached" in result.output.splitlines()
        artifacts = {
            path.read_bytes()
            for path in (workspace / ".dossier" / "cache" / "convert").rglob("*")
            if path.is_file() and not path.name.endswith(".meta.json")
        }
        assert RAW in artifacts

    def test_an_excluded_field_change_keeps_the_first_payload(
        self, workspace: Path, monkeypatch, tracker
    ):
        """Example 4: the one where only `INC-4821`'s rendered HTML changed.

        No new snapshot and the same `snapshot_path`: the projection cannot tell
        the two payloads apart, so the first stays the one held (R2.2).
        """
        (before,) = _rows(workspace, "incidents-jira")
        files = _snapshot_files(workspace)
        tracker.payload, tracker.version = issue("<div>Loss of CHF 48'200</div>"), "v38"

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        (after,) = _rows(workspace, "incidents-jira")
        assert after.snapshot_path == before.snapshot_path
        assert _snapshot_files(workspace) == files

    def test_a_source_without_fields_is_addressed_by_its_content_hash(
        self, workspace: Path, tracker
    ):
        """Counter-example (row 5): the one from `incidents-manual`, declaring no `fields`.

        `snapshot_path` and `content_hash` name the same file: nothing changes
        where the two hashes coincide (R2.10).
        """
        rows = _rows(workspace, "incidents-manual")

        assert rows
        for row in rows:
            assert Path(row.snapshot_path).name == row.content_hash
            assert (workspace / SNAPSHOTS / row.snapshot_path).is_file()
