"""R2.22 — `dossier sync --full <pipeline>` lists every source without a window.

A source that narrows its listings (R1.11) is subtracted from only when sync
asked it for everything, and until now that happened once: the first sync, or a
change to `fields` (R2.3). `--full` asks the same question on demand. It is a
full *listing*, not a re-evaluation: an issue whose version marker is unchanged
is still not fetched (R2.1).

`incidents-jira` here is a tracker that narrows -- it records the `since` it is
asked and answers with what it holds -- with `INC-4821` at `v37` and `INC-4822`
at `v1`, no attachments.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from tests.fakes import register_connector
from tests.pipelines import write_pipeline

from dossier.domain.ports import AttachmentRef, ItemRef, RawItem

PIPELINE = "incident-audit"
INDENT = " " * 6
SOURCE = "incidents-jira"


def issue(key: str) -> bytes:
    return f'{{"key": "{key}", "summary": "About {key}"}}'.encode()


class IssueTracker:
    """A source that narrows: it remembers every `since` it was asked."""

    lists_everything = False

    def __init__(self) -> None:
        self.issues: dict[str, tuple[bytes, str]] = {
            "INC-4821": (issue("INC-4821"), "v37"),
            "INC-4822": (issue("INC-4822"), "v1"),
        }
        self.asked: list[datetime | None] = []
        self.fetched: list[str] = []

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        self.asked.append(since)
        for key in sorted(self.issues):
            yield ItemRef(key=key, remote_version=self.issues[key][1], updated_at=None)

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        payload, version = self.issues[key]
        return RawItem(
            key=key, payload=payload, media_type="application/json", remote_version=version
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _states(workspace: Path) -> dict[str, str]:
    from dossier.infrastructure.ledger import Ledger

    return {row.key: row.state.value for row in Ledger(workspace).rows(SOURCE)}


def _watermark(workspace: Path) -> datetime | None:
    from dossier.infrastructure.ledger import Ledger

    return Ledger(workspace).watermark(SOURCE)


def _under_source(output: str) -> list[str]:
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{SOURCE}  "))
    under = []
    for line in lines[start + 1 :]:
        if not line.startswith(INDENT):
            break
        under.append(line)
    return under


def _source_line(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith(f"{SOURCE}  "))


def _summary(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith("ledger updated"))


@pytest.fixture
def held(workspace: Path, monkeypatch) -> IssueTracker:
    """The tracker synced once, so a watermark exists and `INC-4821` is held."""
    tracker = IssueTracker()
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: issues\n", encoding="utf-8"
    )
    register_connector(monkeypatch, "issues", lambda config, *, workspace: tracker)
    write_pipeline(workspace, sources=[SOURCE])
    first = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert first.exit_code == 0, first.output
    assert tracker.asked == [None]
    assert _watermark(workspace) is not None
    tracker.asked.clear()
    tracker.fetched.clear()
    return tracker


class TestSyncFullTombstonesWhatAWindowedSourceDropped:
    """R2.22 — `--full` is the same question the first sync asked, on demand."""

    def test_a_deleted_issue_is_tombstoned_and_named(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Example 1: the one where `INC-4821` is gone and `--full` finally sees it."""
        del held.issues["INC-4821"]

        result = _cli(workspace, monkeypatch, "sync", "--full", PIPELINE)

        assert result.exit_code == 0, result.output
        assert held.asked == [None]
        assert _states(workspace)["INC-4821"] == "tombstoned"
        assert _under_source(result.output) == [f"{INDENT}INC-4821  tombstoned"]

    def test_a_full_listing_is_not_a_refetch(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Example 2: the one where every marker is unchanged, so nothing is fetched (R2.1)."""
        del held.issues["INC-4821"]

        result = _cli(workspace, monkeypatch, "sync", "--full", PIPELINE)

        assert result.exit_code == 0, result.output
        assert held.fetched == []
        assert "0 fetched" in _source_line(result.output)
        assert "0 new snapshots" in _summary(result.output)

    def test_the_watermark_advances_as_on_any_sync(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Example 3: the one where `--full` asks one question and resets nothing (R2.8)."""
        before = _watermark(workspace)

        result = _cli(workspace, monkeypatch, "sync", "--full", PIPELINE)

        assert result.exit_code == 0, result.output
        after = _watermark(workspace)
        assert after is not None and before is not None
        assert after > before

    def test_without_the_flag_the_listing_is_windowed_and_nothing_is_tombstoned(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Counter-example (row 4): the one where `INC-4821` is legitimately absent.

        A windowed listing omits what did not change (R2.7 row 4).
        """
        del held.issues["INC-4821"]

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert held.asked != [None]
        assert held.asked[0] is not None
        assert _states(workspace)["INC-4821"] == "active"
        assert _under_source(result.output) == []
