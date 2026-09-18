"""R2.13 — sync reports what it did, per source and in total.

The counts are the interface. "Tomorrow's 420 issues cost 20 downloads" is only
credible if the command says so: one line per source, one line in total, and a
source where nothing happened still listed -- a silent source is
indistinguishable from one that was skipped. A failure is not zero work, so it
is reported with its error rather than folded into the counts.

Three sources, synced twice. The issue tracker holds 420 items; before the second
sync 18 of them change and 2 appear. The fixture folder gains `INC-4901.md`, and
the procedures wiki does not move. The 420 are synthetic and numbered for this
test: they stand for the row's volume, not for documents any spec discusses.
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
ISSUES = {f"ISSUE-{number:04d}": "v1" for number in range(1, 421)}
PAGES = {"OPS-114": "v37", "OPS-115": "v12", "OPS-116": "v3"}


class Versioned:
    """A source whose items carry version markers it vouches for, as Jira's do.

    Holds what it is handed and reads it on every call, so a test can change an
    item between two syncs, and can be told to fail a fetch with a given error.
    """

    lists_everything = False

    media_type = "text/markdown"

    def __init__(self, items: dict[str, str]) -> None:
        self.items = dict(items)
        self.failing: dict[str, str] = {}

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.items):
            yield ItemRef(key=key, remote_version=self.items[key], updated_at=None)

    def fetch(self, key: str) -> RawItem:
        if key in self.failing:
            raise ConnectionError(self.failing[key])
        return RawItem(
            key=key,
            payload=f"# {key}\n\nAt version {self.items[key]}.\n".encode(),
            media_type=self.media_type,
            remote_version=self.items[key],
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def sources(workspace: Path, monkeypatch) -> dict[str, Versioned]:
    """The tracker, the fixture folder and the wiki, each synced once already."""
    tracker, wiki = Versioned(ISSUES), Versioned(PAGES)
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: incidents-jira\n"
        "    type: versioned\n"
        "  - id: incidents-manual\n"
        "    type: folder\n"
        "    path: inbox/incidents/\n"
        "  - id: procedures-confluence\n"
        "    type: versioned\n",
        encoding="utf-8",
    )
    register_connector(
        monkeypatch,
        "versioned",
        lambda config, *, workspace: tracker if config.id == "incidents-jira" else wiki,
    )
    write_pipeline(
        workspace,
        sources=["incidents-jira", "incidents-manual"],
        reference=["procedures-confluence"],
    )
    first = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert first.exit_code == 0, first.output
    return {"incidents-jira": tracker, "procedures-confluence": wiki}


def _overnight(workspace: Path, tracker: Versioned) -> None:
    """What changed before the second sync: 18 issues edited, 2 raised, one note filed."""
    for key in sorted(ISSUES)[:18]:
        tracker.items[key] = "v2"
    tracker.items["ISSUE-0421"] = "v1"
    tracker.items["ISSUE-0422"] = "v1"
    (workspace / "inbox" / "incidents" / "INC-4901.md").write_text(
        "# INC-4901\n\nNew since last sync.\n", encoding="utf-8"
    )


def _lines(output: str) -> dict[str, str]:
    return {line.split()[0]: line for line in output.splitlines() if " known · " in line}


class TestSyncReportsCountsPerSource:
    """R2.13 — sync reports what it did, per source and in total."""

    def test_each_source_gets_a_line_of_what_it_cost(
        self, workspace: Path, monkeypatch, sources: dict[str, Versioned]
    ):
        """Example 1: the one where the tracker's 420 issues cost 20 downloads."""
        _overnight(workspace, sources["incidents-jira"])

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert (
            _lines(result.output)["incidents-jira"]
            == "incidents-jira  420 known · 18 changed · 2 new -> 20 fetched"
        )

    def test_the_run_ends_with_what_it_wrote_in_total(
        self, workspace: Path, monkeypatch, sources: dict[str, Versioned]
    ):
        """Example 2: the one ending with 21 new snapshots -- 20 issues and one note."""
        _overnight(workspace, sources["incidents-jira"])

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "ledger updated · 21 new snapshots · 0 tombstoned" in result.output.splitlines()

    def test_a_source_where_nothing_changed_is_still_listed(
        self, workspace: Path, monkeypatch, sources: dict[str, Versioned]
    ):
        """Example 3: the one where the procedures wiki did not move.

        Still listed, reporting `-> 0 fetched`: a silent source is
        indistinguishable from one that was skipped.
        """
        _overnight(workspace, sources["incidents-jira"])

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert (
            _lines(result.output)["procedures-confluence"]
            == "procedures-confluence  3 known · 0 changed · 0 new -> 0 fetched"
        )

    def test_a_failure_is_reported_with_its_error_and_not_counted_as_work(
        self, workspace: Path, monkeypatch, sources: dict[str, Versioned]
    ):
        """Counter-example (row 4): the one where `ISSUE-0422` fails to download.

        Reported as failed, with the error the source gave, and left out of the
        fetched count: a failure is not zero work (R1.9), and a count that
        included it would claim a download that never arrived.
        """
        tracker = sources["incidents-jira"]
        _overnight(workspace, tracker)
        tracker.failing["ISSUE-0422"] = "503 Service Unavailable from the issue tracker"

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 1
        assert (
            _lines(result.output)["incidents-jira"]
            == "incidents-jira  420 known · 18 changed · 1 new -> 19 fetched"
        )
        failure = [line for line in result.output.splitlines() if "ISSUE-0422" in line]
        assert failure and "503 Service Unavailable" in failure[0]
