"""R11.4 — a `dossier sync` or `dossier convert` is one MLflow run of per-source
counts, with no traces.

The unit test beside this one proves `count_metrics`: a pure mapping from counts
to the names they are recorded under. It touches no tracker and runs no command,
and it is true whether or not anything ever records. So nothing proved either
command records, which `/verify` found the hard way -- `dossier convert` never
builds a tracker at all, and prints its per-source counts without sending them.

Sync's half below is expected to pass the moment it is written. That is the
point: sync was wired all along and simply unproved, and a gap in proof is worth
closing before it becomes a gap in behaviour -- which is exactly what happened to
convert.

Tracking is switched on the way a person switches it on, in the environment
(R10.1), and only after the first sync, so the runs under test are the ones each
test makes.
"""

from __future__ import annotations

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
    """The three fixture documents held, with tracking still off.

    Off on purpose: this sync is setup, and a tracker switched on before it would
    hold a run every assertion below would then have to skip past.
    """
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


class TestSyncAndConvertRecordToMLflow:
    """R11.4 — one MLflow run of per-source counts, with no traces."""

    def test_a_sync_records_the_per_source_counts_it_prints(
        self, synced: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 1's shape, and the counter-example (row 3) in one run.

        The second sync over an unchanged source: recorded with its zeros rather
        than omitted, because a source missing from the record is
        indistinguishable from one that was skipped (R2.13).

        `fetched` is 3 and not 0, which is the one number here worth pausing on.
        A folder source reports no `remote_version` (R1.5), so change detection
        falls through to hashing the payload -- and hashing it means reading it.
        Nothing changed, so 0 snapshots were written; all 3 were still fetched to
        find that out. Spec 002 says so outright: "fetches zero payloads" is
        unreachable for this source, while "writes zero snapshots" holds
        everywhere (R2.5).
        """
        result = _run(synced, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1, "one sync is one MLflow run"
        assert tracker.runs[0].metrics == {
            f"{SOURCE}/known": 3,
            f"{SOURCE}/changed": 0,
            f"{SOURCE}/new": 0,
            f"{SOURCE}/returned": 0,
            f"{SOURCE}/fetched": 3,
            f"{SOURCE}/failed": 0,
        }

    def test_a_convert_records_the_per_source_counts_it_prints(
        self, synced: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one converting three held documents, none cached.

        The figures `dossier convert` already prints (R8.8), recorded under the
        same names. Before this rule was wired the command printed them and sent
        nothing, and exited 0 doing it.
        """
        result = _run(synced, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1, "one convert is one MLflow run"
        assert tracker.runs[0].metrics == {
            f"{SOURCE}/held": 3,
            f"{SOURCE}/converted": 3,
            f"{SOURCE}/cached": 0,
            f"{SOURCE}/failed": 0,
            f"{SOURCE}/left_out": 0,
        }

    def test_neither_command_records_a_trace(
        self, synced: Path, monkeypatch, tracker: FakeTracker
    ):
        """The half of the title nothing asserted: counts, and no traces.

        A trace is one (step, document), the unit of a cache key (spec 011).
        Neither of these commands runs a step, so a trace here would be a record
        of work that never happened.
        """
        assert _run(synced, monkeypatch, "sync", PIPELINE).exit_code == 0
        assert _run(synced, monkeypatch, "convert", PIPELINE).exit_code == 0

        assert len(tracker.runs) == 2
        assert tracker.traces == []
        assert tracker.spans == []
