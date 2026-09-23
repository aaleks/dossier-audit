"""R10.23 — MLflow writes nothing to a command's terminal.

Never before the record it is closing, above all.

`MlflowClient.set_terminated` prints an emoji to standard output before it sends
the update that closes a run. Where standard output is `cp1252` -- a Windows
console redirected to a file or a pipe -- the print raised, the update was never
sent, and the run stayed `RUNNING` for ever behind a clean exit 0.

The real `MlflowClient` runs here. `requests` is answered at its adapter and the
startup check at `HEALTH_TRANSPORT`, so no socket is opened.
"""

from __future__ import annotations

import io
import os
import sys

import httpx
import pytest

from dossier.domain.tracking import MlflowAuth
from dossier.infrastructure.tracking import mlflow as adapter

pytest.importorskip("mlflow")

URI = "http://127.0.0.1:5077"


@pytest.fixture
def sent(monkeypatch) -> list:
    """Every request MLflow would have put on the wire, each answered `{}` with a 200."""
    import requests
    from requests.adapters import HTTPAdapter

    prepared: list = []

    def answer(self, request, **kwargs):
        prepared.append(request)
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        response.headers["Content-Type"] = "application/json"
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(HTTPAdapter, "send", answer)
    monkeypatch.setattr(
        adapter, "HEALTH_TRANSPORT", httpx.MockTransport(lambda request: httpx.Response(200))
    )
    return prepared


def piped(monkeypatch) -> io.TextIOWrapper:
    """Standard output as a Windows pipe has it: `cp1252`, strict.

    Called from a test's body, not as a fixture: pytest's capture puts its own
    `sys.stdout` back when the call phase starts, which silently undid this
    replacement and let the test pass against the unfixed code.
    """
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    return stdout


@pytest.fixture(autouse=True)
def mlflow_left_alone(monkeypatch):
    """Building a tracker points MLflow's process-wide URI; a test leaves it as it was."""
    import mlflow

    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)


class TestMlflowWritesNothingToTheTerminal:
    """R10.23 — what a command prints is dossier's."""

    def test_a_run_closes_with_standard_output_piped(self, sent, monkeypatch):
        """Example 1: the one where the emoji used to stop the update being sent."""
        piped(monkeypatch)
        tracker = adapter.connect(URI, auth=MlflowAuth())
        tracker._run_id = "4e49d64a5bb444ed90b6b2d21dc10df7"

        tracker.end_run(status="FINISHED")

        assert [request.path_url for request in sent][-1] == "/api/2.0/mlflow/runs/update"

    def test_nothing_is_written_to_standard_output(self, sent, monkeypatch):
        """Example 2: the one with no `🏃 View run` line in a person's terminal."""
        stdout = piped(monkeypatch)
        tracker = adapter.connect(URI, auth=MlflowAuth())
        tracker._run_id = "4e49d64a5bb444ed90b6b2d21dc10df7"

        tracker.end_run(status="FINISHED")

        stdout.flush()
        assert stdout.buffer.getvalue() == b""

    def test_the_registries_quiet_mlflow_too(self, sent):
        """Example 2, on the path `dossier run` links prompts through, unprobed (R14.7)."""
        adapter.connect_prompts(URI, auth=MlflowAuth(), verify=False)

        from mlflow.environment_variables import MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT

        assert MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT.get() is True

    def test_tracking_off_leaves_mlflows_setting_as_it_was(self, monkeypatch):
        """Counter-example 4: the one where nothing records, so nothing is configured."""
        from dossier.domain.tracking import settings

        monkeypatch.delenv("MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT", raising=False)

        assert settings({}) is None
        assert "MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT" not in os.environ
