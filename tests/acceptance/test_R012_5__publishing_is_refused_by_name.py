"""R012.5 — publishing with tracking off, or to a server that cannot hold a
dataset, is refused by name before anything is sent.

Four ways a machine is not set up to hold a dataset, and each is refused naming the
one thing to change. Refused rather than absorbed, because unlike every other
command this one's whole output is the record: a publish that quietly did nothing
would leave a person looking for a dataset that was never sent.

The FileStore case is the one this rule exists for. Every other record `dossier`
sends works against a file-backed MLflow server; a dataset does not, because
evaluation datasets live in tables. A person who finds that out as an MLflow
traceback has to go and read MLflow's source to learn which server flag to change.

The server is answered by an `httpx.MockTransport`, so no socket is opened.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.fakes import FakeDatasetRegistry
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
GOLD = "gold/incidents"
URI = "http://localhost:5000"
DATASETS = "/api/3.0/mlflow/datasets/search"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _publish(workspace: Path, monkeypatch, gold: str = GOLD):
    return _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", gold)


def _answering(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.fixture
def configured(workspace: Path, monkeypatch) -> Path:
    """A workspace with a pipeline and a gold set, and tracking not yet decided."""
    write_pipeline(workspace, sources=["incidents-jira"])
    return workspace


@pytest.fixture
def enabled(configured: Path, monkeypatch) -> Path:
    """Tracking switched on, pointing at a server the test decides the behaviour of."""
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    return configured


class TestPublishingIsRefusedByName:
    """R12.5 — publishing is refused by name before anything is sent."""

    def test_tracking_switched_off_refuses_and_names_the_variable(
        self, configured: Path, monkeypatch
    ):
        """Example 1: the one where the machine records nothing at all.

        A run with tracking off still runs, and is right to. A publish with
        tracking off has nowhere to publish to, so it says so instead of
        succeeding at nothing.
        """
        import dossier.cli.main as cli

        registry = FakeDatasetRegistry()
        monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: registry)

        result = _publish(configured, monkeypatch)

        assert result.exit_code == 2, result.output
        assert "DOSSIER_MLFLOW_ENABLED" in result.output
        assert registry.publishes == [], "nothing sent"

    def test_a_server_that_cannot_hold_a_dataset_names_the_sql_backend(
        self, enabled: Path, monkeypatch
    ):
        """Example 2: the one where the server is a FileStore.

        The health check passes — it is a real, working MLflow server — and the
        dataset endpoint is simply not there. Naming the SQL backend is the whole
        value of this check: the fix is a flag on the server, not anything in the
        workspace.
        """
        from dossier.infrastructure.tracking import mlflow as tracking

        def file_store(request: httpx.Request) -> httpx.Response:
            if request.url.path == DATASETS:
                return httpx.Response(404, text="Not Found")
            return httpx.Response(200, json={"status": "OK"})

        monkeypatch.setattr(tracking, "HEALTH_TRANSPORT", _answering(file_store))

        result = _publish(enabled, monkeypatch)

        assert result.exit_code == 2, result.output
        assert "--backend-store-uri" in result.output
        assert "sqlite" in result.output

    def test_an_unreachable_server_names_the_uri(self, enabled: Path, monkeypatch):
        """Example 3: the one where nothing is listening.

        The same refusal R10.5 row 1 gives a run, for the same reason: the thing
        to fix is the server, and the message says which one.
        """
        from dossier.infrastructure.tracking import mlflow as tracking

        def nothing_listening(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        monkeypatch.setattr(tracking, "HEALTH_TRANSPORT", _answering(nothing_listening))

        result = _publish(enabled, monkeypatch)

        assert result.exit_code == 2, result.output
        assert URI in result.output

    def test_a_gold_directory_that_is_not_there_is_refused(self, enabled: Path, monkeypatch):
        """The one where the gold set was mistyped.

        Named as typed. A publish that created an empty dataset called `incident`
        because someone dropped an `s` would be worse than a refusal, and harder
        to notice.
        """
        import dossier.cli.main as cli

        registry = FakeDatasetRegistry()
        monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: registry)

        result = _publish(enabled, monkeypatch, gold="gold/incident")

        assert result.exit_code == 2, result.output
        assert "gold/incident" in result.output
        # A directory that is not there and one holding no answers want different
        # fixes -- a corrected path, or a reviewer -- so they do not share a message.
        assert "no gold set" in result.output
        assert "no verified answers" not in result.output
        assert registry.publishes == [], "nothing sent"

    def test_an_eval_against_a_file_store_server_still_scores(self, enabled: Path, monkeypatch):
        """Counter-example (row 5): the one where the same server is fine for an eval.

        An eval needs no dataset; only publishing does. So the check that refuses
        a publish must not sit anywhere an eval passes through, and this is what
        says so — the same FileStore server, and the command exits 0.
        """
        from dossier.infrastructure.tracking import mlflow as tracking

        def file_store(request: httpx.Request) -> httpx.Response:
            if request.url.path == DATASETS:
                return httpx.Response(404, text="Not Found")
            return httpx.Response(200, json={"status": "OK"})

        monkeypatch.setattr(tracking, "HEALTH_TRANSPORT", _answering(file_store))

        result = _cli(enabled, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
