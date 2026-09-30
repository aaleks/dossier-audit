"""R11.32 — a `dossier status` records nothing, and needs no server.

`status` changes nothing (R17.5), and a command that changes nothing records
nothing, as `--plan` and `gc`'s preview do not (R11.28 row 4). So it does not
check for a server either: R10.5 refuses a command whose record would be lost,
and `status` has none to lose.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from tests.acceptance.test_R010_5__an_unreachable_server_refuses_before_any_work import (
    URI,
    _server_down,
    _tracking_on,
)
from tests.acceptance.test_R017_7__status_says_what_eval_will_withhold import (
    GOLD,
    _cli,
    audited_workspace,
)
from tests.fakes import FakeTracker
from tests.scoring_example import PIPELINE


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """R17.7's workspace: synced and run, a bar and a sample beside the gold set."""
    return audited_workspace(workspace, monkeypatch)


def _status(workspace: Path, monkeypatch):
    return _cli(workspace, monkeypatch, "status", PIPELINE, "--gold", GOLD)


class TestStatusRecordsNothing:
    """R11.32 — no record, and so no server asked for."""

    def test_status_with_tracking_on_records_no_run(self, audited: Path, monkeypatch):
        """Row 1 — the one with tracking on and a server to record to."""
        import dossier.cli.bootstrap as cli

        tracker = FakeTracker()
        _tracking_on(monkeypatch)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)

        result = _status(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        assert tracker.runs == []
        assert "recorded to MLflow" not in result.output

    def test_an_unreachable_server_does_not_stop_it(self, audited: Path, monkeypatch):
        """Row 2, counter-example — the one with nothing answering at the tracking URI."""
        _tracking_on(monkeypatch)
        _server_down(monkeypatch)

        result = _status(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        assert URI not in result.output
        assert result.output.startswith("sources\n")

    def test_a_missing_tracking_extra_does_not_stop_it(self, audited: Path, monkeypatch):
        """Row 3, counter-example — the one switched on without `mlflow` installed."""
        _tracking_on(monkeypatch)
        monkeypatch.setitem(sys.modules, "mlflow", None)

        result = _status(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        assert "dossier[tracking]" not in result.output
