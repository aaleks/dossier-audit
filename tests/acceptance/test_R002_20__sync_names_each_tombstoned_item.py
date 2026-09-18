"""R2.20 — `dossier sync` names each item it tombstones under its source line.

`1 tombstoned` has the same problem as `1 changed`: it says something left and
not what.

Tombstoning is computed only against a full listing (R2.7 row 4), and after a
first sync there is a watermark, so every later listing is incremental unless
the source's projection changed and everything must be re-evaluated (R2.3). The
tests here force a full listing the one way a workspace can: by changing the
source's `fields`. `incidents-jira` declares `fields: [key, summary]` and holds
`INC-4821` and `INC-4822` with no attachments.
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
    return f'{{"key": "{key}", "summary": "About {key}", "rendered": "<p>{key}</p>"}}'.encode()


class IssueTracker:
    """Two issues at version markers it vouches for; a test removes and restores them."""

    lists_everything = False

    def __init__(self) -> None:
        self.issues: dict[str, tuple[bytes, str]] = {
            "INC-4821": (issue("INC-4821"), "v37"),
            "INC-4822": (issue("INC-4822"), "v1"),
        }

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.issues):
            yield ItemRef(key=key, remote_version=self.issues[key][1], updated_at=None)

    def fetch(self, key: str) -> RawItem:
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


def _declare(workspace: Path, fields: str) -> None:
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: issues\n    fields: [{fields}]\n",
        encoding="utf-8",
    )


def _tombstoned_lines(output: str) -> list[str]:
    """The indented lines under the source's count line that name a tombstone."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{SOURCE}  "))
    under = []
    for line in lines[start + 1 :]:
        if not line.startswith(INDENT):
            break
        under.append(line)
    return [line for line in under if line.endswith("  tombstoned")]


def _summary(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith("ledger updated"))


@pytest.fixture
def held(workspace: Path, monkeypatch) -> IssueTracker:
    """The tracker synced once under `fields: [key, summary]`."""
    tracker = IssueTracker()
    _declare(workspace, "key, summary")
    register_connector(monkeypatch, "issues", lambda config, *, workspace: tracker)
    write_pipeline(workspace, sources=[SOURCE])
    first = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert first.exit_code == 0, first.output
    return tracker


class TestSyncNamesEachTombstonedItem:
    """R2.20 — sync names each item it tombstones under its source line."""

    def test_an_item_absent_from_a_full_listing_is_named(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Example 1: the one where `INC-4821` left, and the full listing says so."""
        del held.issues["INC-4821"]
        _declare(workspace, "key, summary, description")

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _tombstoned_lines(result.output) == [f"{INDENT}INC-4821  tombstoned"]

    def test_two_departures_are_two_lines_in_key_order_and_the_count_still_holds(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Example 2: the one where both issues left -- named, and still counted (R2.13)."""
        held.issues.clear()
        _declare(workspace, "key, summary, description")

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _tombstoned_lines(result.output) == [
            f"{INDENT}INC-4821  tombstoned",
            f"{INDENT}INC-4822  tombstoned",
        ]
        assert _summary(result.output).endswith("· 2 tombstoned")

    def test_an_incremental_listing_tombstones_and_names_nothing(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Counter-example (row 3): the one where `INC-4821` is absent from a windowed listing.

        Legitimately absent -- an incremental listing omits what did not change --
        so nothing is tombstoned (R2.7 row 4), and nothing is named.
        """
        del held.issues["INC-4821"]

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _summary(result.output).endswith("· 0 tombstoned")
        assert _tombstoned_lines(result.output) == []

    def test_an_item_returning_with_the_same_bytes_is_not_named(
        self, workspace: Path, monkeypatch, held: IssueTracker
    ):
        """Counter-example (row 4): the one where `INC-4821` comes back unchanged (R2.7 row 3).

        Not tombstoned, so R2.20 has nothing to say; and its hash did not move,
        so R2.18 has nothing to say either.
        """
        gone = held.issues.pop("INC-4821")
        _declare(workspace, "key, summary, description")
        departed = _cli(workspace, monkeypatch, "sync", PIPELINE)
        assert _tombstoned_lines(departed.output) == [f"{INDENT}INC-4821  tombstoned"]

        held.issues["INC-4821"] = gone
        _declare(workspace, "key, summary")
        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _summary(result.output).endswith("· 0 tombstoned")
        assert not [line for line in result.output.splitlines() if "INC-4821" in line]
