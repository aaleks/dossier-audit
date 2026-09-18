"""R10.9 — the tracker points MLflow at the configured server before it records
anything.

MLflow has two paths out. A run is written through the `MlflowClient` dossier
constructs with the URI; a trace is exported by MLflow's own asynchronous
exporter, which reads the library's process-wide configuration rather than that
client. Left unset, traces go to MLflow's default local store -- where the
experiment the client just created does not exist -- and are dropped with a
warning while the run itself records perfectly. R11.1 and R11.2 are then claims
about traces nobody can read.

Nothing here opens a socket: `MlflowClient` is lazy, and both MLflow calls are
replaced.
"""

from __future__ import annotations

import pytest

from dossier.infrastructure.tracking.mlflow import MlflowTracker

URI = "http://localhost:5000"
ANOTHER = "http://elsewhere:5000"


@pytest.fixture
def recorded(monkeypatch) -> list[str]:
    """What MLflow was told its tracking URI is, in order."""
    import mlflow

    told: list[str] = []
    monkeypatch.setattr(mlflow, "set_tracking_uri", told.append)
    monkeypatch.setattr(mlflow, "MlflowClient", lambda tracking_uri=None: object())
    return told


class TestTheTrackerPointsMlflowAtTheConfiguredServer:
    """R10.9 — one server, for records and traces alike."""

    def test_building_a_tracker_configures_mlflow(self, recorded: list[str]):
        """Example 1: the one built for `http://localhost:5000`.

        Before the first record, because the first thing a command does with a
        tracker is start a run, and a trace exported to the wrong store cannot
        be moved afterwards.
        """
        MlflowTracker(URI)

        assert recorded == [URI]

    def test_mlflows_own_variable_decides_nothing(self, recorded: list[str], monkeypatch):
        """Example 2: the one with `MLFLOW_TRACKING_URI` left in the shell.

        Dossier's own configuration wins, because MLflow's variables are not
        read at all (R10.1 row 5) -- a shell left over from another project must
        not redirect this project's records.
        """
        monkeypatch.setenv("MLFLOW_TRACKING_URI", ANOTHER)

        MlflowTracker(URI)

        assert recorded == [URI]

    def test_tracking_off_configures_nothing(self, recorded: list[str]):
        """Counter-example (row 4): the one where tracking is off.

        No tracker is built, so MLflow's configuration is left exactly as it
        was. `settings()` returning `None` is what makes that structural rather
        than remembered: a caller handed nothing to record with cannot record,
        and cannot reconfigure anything either (R10.1).
        """
        from dossier.domain.tracking import settings

        assert settings({}) is None
        assert recorded == []
