"""R10.19 — an OIDC access token is fetched before any work, and fetched again once no more
than the refresh margin remains.

The half a person meets at the command line: the exchange happens before the
startup check, the check carries the token it returned, and an identity provider
that refuses the client -- or is not there -- stops the command before any work,
naming what to fix and never the secret. When the token is fetched again is the
unit test's, against a clock passed in.

Keycloak's token endpoint and MLflow are both `httpx.MockTransport`s. Past the
check the tracker is a `FakeTracker`. No socket is opened.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from tests.fakes import FakeTracker, NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

URI = "https://mlflow.example.internal"
TOKEN_URL = "https://sso.example.internal/realms/dossier/protocol/openid-connect/token"
SECRET = "client-secret-7f3a"
ACCESS = "eyJhbGciOiJSUzI1NiJ9.access.token"


class Keycloak:
    """A realm's token endpoint, answering the client-credentials grant."""

    def __init__(self, *, refuse: bool = False) -> None:
        self.refuse = refuse
        self.forms: list[dict[str, list[str]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.forms.append(parse_qs(request.content.decode()))
        if self.refuse:
            return httpx.Response(
                401,
                # What a live Keycloak 26 answers a wrong secret: not the
                # `invalid_client` RFC 6749 suggests, and not what this fake first
                # said. dossier keys on the status, so either passes.
                json={
                    "error": "unauthorized_client",
                    "error_description": "Invalid client or Invalid client credentials",
                },
            )
        return httpx.Response(
            200, json={"access_token": ACCESS, "expires_in": 300, "token_type": "Bearer"}
        )


class Mlflow:
    """MLflow behind a proxy that accepts only the token Keycloak issued."""

    def __init__(self) -> None:
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.headers.get("Authorization") != f"Bearer {ACCESS}":
            return httpx.Response(401)
        return httpx.Response(200, json={})


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


def _oidc(monkeypatch, keycloak, mlflow: Mlflow) -> None:
    """Tracking on at `URI`, as the `dossier-ci` client of the `dossier` realm."""
    import dossier.infrastructure.tracking.mlflow as adapter
    import dossier.infrastructure.tracking.oidc as oidc

    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setenv("DOSSIER_MLFLOW_AUTH", "oidc")
    monkeypatch.setenv("DOSSIER_MLFLOW_OIDC_TOKEN_URL", TOKEN_URL)
    monkeypatch.setenv("DOSSIER_MLFLOW_OIDC_CLIENT_ID", "dossier-ci")
    monkeypatch.setenv("DOSSIER_MLFLOW_OIDC_CLIENT_SECRET", SECRET)
    monkeypatch.setattr(oidc, "TOKEN_TRANSPORT", httpx.MockTransport(keycloak))
    monkeypatch.setattr(adapter, "HEALTH_TRANSPORT", httpx.MockTransport(mlflow))
    monkeypatch.setattr(adapter, "MlflowTracker", lambda uri: FakeTracker())


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


class TestATokenEndpointThatRefusesRefusesBeforeAnyWork:
    """R10.19 — a token before any work, and a refused client refused before any work."""

    def test_one_token_before_the_check_and_the_check_carries_it(self, held: Path, monkeypatch):
        """Example 1: the one where Keycloak answers `expires_in: 300`.

        One exchange, before the startup check, whose form holds the grant and
        the client and nothing else. The check -- and so every request after it
        (R10.17) -- carries the token that came back.
        """
        keycloak, mlflow = Keycloak(), Mlflow()
        _oidc(monkeypatch, keycloak, mlflow)

        result = _cli(held, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert keycloak.forms == [
            {
                "grant_type": ["client_credentials"],
                "client_id": ["dossier-ci"],
                "client_secret": [SECRET],
            }
        ]
        assert mlflow.asked, "the startup check ran"
        assert {r.headers["Authorization"] for r in mlflow.asked} == {f"Bearer {ACCESS}"}

    def test_a_refused_client_refuses_the_run_naming_the_client_and_never_the_secret(
        self, held: Path, monkeypatch
    ):
        """Example 6: the one where Keycloak answers 401 `unauthorized_client`."""
        mlflow = Mlflow()
        _oidc(monkeypatch, Keycloak(refuse=True), mlflow)

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert TOKEN_URL in result.output
        assert "DOSSIER_MLFLOW_OIDC_CLIENT_ID" in result.output
        assert "DOSSIER_MLFLOW_OIDC_CLIENT_SECRET" in result.output
        assert SECRET not in result.output
        assert mlflow.asked == [], "refused before MLflow was asked anything"
        assert not (held / "runs").exists(), "no run directory"

    def test_an_identity_provider_that_is_not_there_is_named(self, held: Path, monkeypatch):
        """Example 7: the one where nothing answers at the token URL."""
        _oidc(monkeypatch, _unreachable, Mlflow())

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "DOSSIER_MLFLOW_OIDC_TOKEN_URL" in result.output
        assert not (held / "runs").exists()
