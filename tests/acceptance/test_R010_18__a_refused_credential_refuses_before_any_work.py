"""R10.18 — a server that refuses the credential refuses the command before any work.

MLflow's own basic auth leaves `/health` unauthenticated -- confirmed live against
`mlflow server --app-name basic-auth`, where `/health` answered 200 and
`/api/2.0/mlflow/experiments/search` answered 401 to the same anonymous client.
So R10.5's check passed with a credential every later record would fail, and a
run of model calls went unrecorded. The check now makes one read that needs the
credential, with the credential.

The server is an `httpx.MockTransport` answering the way that live server did.
Past the check, the tracker is a `FakeTracker`: what this rule decides is whether
the command starts, not what it records. No socket is opened.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
from tests.fakes import (
    FakePromptRegistry,
    FakeTracker,
    FakeVersionRegistry,
    NoModelClient,
    register_connector,
)
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

URI = "https://mlflow.example.internal"
LOGIN = "https://sso.example.internal/realms/dossier/protocol/openid-connect/auth"
PASSWORD = "correct-horse-battery-staple"
WRONG = "not-the-password-0000"
ACCEPTED = "Basic " + base64.b64encode(f"dossier-ci:{PASSWORD}".encode()).decode()


class Server:
    """MLflow behind its own basic auth: `/health` open, the API behind the pair."""

    def __init__(self, *, redirect_to: str | None = None) -> None:
        self.redirect_to = redirect_to
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if self.redirect_to is not None:
            return httpx.Response(302, headers={"Location": self.redirect_to})
        if request.url.path == "/health":
            return httpx.Response(200, text="OK")
        if request.headers.get("Authorization") != ACCEPTED:
            return httpx.Response(401, text="You are not authenticated.")
        return httpx.Response(200, json={"experiments": []})


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def held(workspace: Path, monkeypatch) -> Path:
    """The four incidents synced with tracking off, so a run has real work to refuse."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return workspace


def _run_registries_are_fakes(monkeypatch) -> None:
    """A run that got past the check links a version and its prompts; not to a real server.

    Before this rule the check passed, the run went on, and the real registries
    retried against the suite's blocked sockets for minutes. A red test should
    fail on its assertion, not on a timeout.
    """
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_version_registry", lambda settings: FakeVersionRegistry())
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: FakePromptRegistry(), raising=False
    )


def _serve(monkeypatch, server: Server, *, password: str | None) -> Server:
    """Tracking on at `URI`, as `dossier-ci` with `password`, or with no mode at all."""
    import dossier.infrastructure.tracking.mlflow as adapter

    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    if password is not None:
        monkeypatch.setenv("DOSSIER_MLFLOW_AUTH", "basic")
        monkeypatch.setenv("DOSSIER_MLFLOW_AUTH_USERNAME", "dossier-ci")
        monkeypatch.setenv("DOSSIER_MLFLOW_AUTH_PASSWORD", password)
    monkeypatch.setattr(adapter, "HEALTH_TRANSPORT", httpx.MockTransport(server))
    monkeypatch.setattr(adapter, "MlflowTracker", lambda uri: FakeTracker())
    return server


class TestARefusedCredentialRefusesBeforeAnyWork:
    """R10.18 — a server that refuses the credential refuses the command before any work."""

    def test_the_right_password_is_checked_and_the_command_proceeds(
        self, held: Path, monkeypatch
    ):
        """Example 1: the one where `/health` and the read both answer 200.

        Also row 6: `dossier-ci` may hold only READ, and the command still
        proceeds. A read cannot prove write access; the first refused write is
        R10.22's to report.
        """
        server = _serve(monkeypatch, Server(), password=PASSWORD)

        result = _cli(held, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        read = [request for request in server.asked if request.url.path != "/health"]
        assert read, "the check made a read that needs the credential"
        assert all(request.headers["Authorization"] == ACCEPTED for request in server.asked)

    def test_the_wrong_password_refuses_the_run_naming_both_variables(
        self, held: Path, monkeypatch
    ):
        """Example 2: the one where `/health` says 200 and the read says 401."""
        _serve(monkeypatch, Server(), password=WRONG)

        _run_registries_are_fakes(monkeypatch)

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert URI in result.output
        assert "401" in result.output
        assert "DOSSIER_MLFLOW_AUTH_USERNAME" in result.output
        assert "DOSSIER_MLFLOW_AUTH_PASSWORD" in result.output
        assert WRONG not in result.output
        assert not (held / "runs").exists(), "no run directory"

    def test_no_mode_against_a_server_that_wants_one_says_so(self, held: Path, monkeypatch):
        """Example 3: the one where the server wants a credential and none was chosen."""
        _serve(monkeypatch, Server(), password=None)

        _run_registries_are_fakes(monkeypatch)

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "DOSSIER_MLFLOW_AUTH" in result.output
        assert "not set" in result.output
        assert not (held / "runs").exists()

    def test_a_redirect_to_a_login_page_is_named_as_one(self, held: Path, monkeypatch):
        """Example 4: the one behind a proxy that sends a command to Keycloak's login page."""
        _serve(monkeypatch, Server(redirect_to=LOGIN), password=PASSWORD)

        _run_registries_are_fakes(monkeypatch)

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert LOGIN in result.output
        assert "no MLflow server answers" not in result.output
        assert not (held / "runs").exists()

    @pytest.mark.parametrize(
        "command",
        [
            ("dataset", "publish", PIPELINE, "--gold", "gold/incidents"),
            ("prompts", "publish", PIPELINE),
        ],
        ids=["dataset-publish", "prompts-publish"],
    )
    def test_every_command_that_connects_makes_the_same_check(
        self, held: Path, monkeypatch, command
    ):
        """Example 5: the one where the wrong password meets a publish, not a run."""
        _serve(monkeypatch, Server(), password=WRONG)

        result = _cli(held, monkeypatch, *command)

        assert result.exit_code == 2, result.output
        assert "401" in result.output
        assert "DOSSIER_MLFLOW_AUTH_PASSWORD" in result.output

    def test_a_local_store_is_not_asked(self, held: Path, monkeypatch):
        """Counter-example 7: the one with `sqlite:///mlflow.db`, which no request reaches."""
        server = _serve(monkeypatch, Server(), password=WRONG)
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")

        result = _cli(held, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert server.asked == []
