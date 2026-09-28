"""R11.26, at the CLI — a convert that leaves the JSON out records `/left_out`.

R8.27's folder: an exported page, a register and `PLAY-4006-indexer-alerts.json`,
with `convert: {application/json: []}`. Its line reads
`3 held · 2 converted · 0 cached · 1 left out`, and the record now holds the
same numbers. Tracking is switched on after the sync, as a person switches it
on (R10.1).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tests.fakes import FakeTracker
from tests.pipelines import write_pipeline

PIPELINE = "export-audit"
SOURCE = "incidents-exports"
URI = "http://localhost:5000"

EXPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "exports"
PAGE = "PLAY-4001-payment-retries.html"
REGISTER = "PLAY-4004-incident-register.csv"
ALERTS = "PLAY-4006-indexer-alerts.json"
LEAVE_JSON_OUT = "    convert:\n      application/json: []\n"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _synced(workspace: Path, monkeypatch, *, convert: str) -> Path:
    """The three exports, synced under a source declaring `convert` as given."""
    inbox = workspace / "inbox" / "exports"
    inbox.mkdir(parents=True)
    for name in (PAGE, REGISTER, ALERTS):
        shutil.copy(EXPORTS / name, inbox / name)
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: folder\n    path: inbox/exports/\n{convert}",
        encoding="utf-8",
    )
    write_pipeline(workspace, name=PIPELINE, sources=[SOURCE])
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    return workspace


def _tracked(monkeypatch) -> FakeTracker:
    """Tracking switched on after the sync, recording to a fake that counts."""
    import dossier.cli.bootstrap as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


class TestConvertRecordsTheLeftOutCount:
    """R11.26 — the numbers the line prints, `left out` among them."""

    def test_the_json_left_out_is_counted_in_the_record(self, workspace: Path, monkeypatch):
        """Row 1: the one where 2 converted and 1 left out account for 3 held."""
        _synced(workspace, monkeypatch, convert=LEAVE_JSON_OUT)
        tracker = _tracked(monkeypatch)

        result = _cli(workspace, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "3 held · 2 converted · 0 cached · 1 left out" in result.output
        [run] = tracker.runs
        assert run.metrics == {
            f"{SOURCE}/held": 3,
            f"{SOURCE}/converted": 2,
            f"{SOURCE}/cached": 0,
            f"{SOURCE}/failed": 0,
            f"{SOURCE}/left_out": 1,
        }

    def test_converted_again_it_is_left_out_again_and_never_cached(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where the second convert serves two from the cache."""
        _synced(workspace, monkeypatch, convert=LEAVE_JSON_OUT)
        tracker = _tracked(monkeypatch)
        assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 0, result.output
        second = tracker.runs[-1].metrics
        assert (
            second[f"{SOURCE}/converted"],
            second[f"{SOURCE}/cached"],
            second[f"{SOURCE}/left_out"],
        ) == (0, 2, 1)

    def test_a_source_that_names_nothing_to_leave_out_records_a_zero(
        self, workspace: Path, monkeypatch
    ):
        """Counter-example (row 3): the one where the JSON fails instead (R8.25)."""
        _synced(workspace, monkeypatch, convert="")
        tracker = _tracked(monkeypatch)

        result = _cli(workspace, monkeypatch, "convert", PIPELINE)

        assert result.exit_code != 0, result.output
        [run] = tracker.runs
        assert (run.metrics[f"{SOURCE}/failed"], run.metrics[f"{SOURCE}/left_out"]) == (1, 0)
