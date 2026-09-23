"""R10.20 — `DOSSIER_MLFLOW_CA_BUNDLE`, when set, is what every request to MLflow and to its
token endpoint is verified against.

A server signed by a private CA is trusted on all three connections dossier
makes: its own startup check, the OIDC token exchange, and MLflow's requests,
which read `MLFLOW_TRACKING_SERVER_CERT_PATH`. The fixture CA is a public
certificate generated for these tests; no key is committed.

No socket is opened: `httpx` is answered by a `MockTransport`, and what matters
is what each client was *built* to trust, which is recorded as it is built.
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path

import httpx
import pytest

from dossier.domain.tracking import MlflowAuth, settings
from dossier.infrastructure.tracking import mlflow as adapter

pytest.importorskip("mlflow")

URI = "https://mlflow.example.internal"
BUNDLE = "certs/example-internal.crt"
CA = "dossier example.internal test CA"
TOKEN_URL = "https://sso.example.internal/realms/dossier/protocol/openid-connect/token"


@pytest.fixture
def trusted(monkeypatch) -> list[object]:
    """What each `httpx.Client` dossier builds is told to verify against, in order."""
    built: list[object] = []
    real = httpx.Client

    class Recording(real):
        def __init__(self, *args, **kwargs):
            built.append(kwargs.get("verify", True))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", Recording)
    return built


@pytest.fixture(autouse=True)
def server(monkeypatch, workspace: Path) -> None:
    """MLflow and Keycloak both answering 200, from the fixture workspace."""
    import mlflow

    from dossier.infrastructure.tracking import oidc

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        return httpx.Response(200, json={})

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(adapter, "HEALTH_TRANSPORT", httpx.MockTransport(answer))
    monkeypatch.setattr(oidc, "TOKEN_TRANSPORT", httpx.MockTransport(answer))
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)


def issuers(verify: object) -> list[str]:
    """The common names of the CAs an `ssl.SSLContext` trusts."""
    assert isinstance(verify, ssl.SSLContext), verify
    return [
        value
        for cert in verify.get_ca_certs()
        for rdn in cert["subject"]
        for key, value in rdn
        if key == "commonName"
    ]


class TestAPrivateCaIsTrustedOnEveryRequest:
    """R10.20 — one bundle, on every connection dossier makes."""

    def test_the_variable_is_read(self):
        """Example 1's configuration: the path, as given."""
        found = settings(
            {
                "DOSSIER_MLFLOW_ENABLED": "true",
                "DOSSIER_MLFLOW_TRACKING_URI": URI,
                "DOSSIER_MLFLOW_CA_BUNDLE": BUNDLE,
            }
        )

        assert found.ca_bundle == BUNDLE

    def test_the_startup_check_and_mlflow_both_trust_the_bundle(self, trusted):
        """Example 1: the one where `https://mlflow.example.internal` is signed by that CA."""
        from mlflow.utils.credentials import get_default_host_creds

        adapter.connect(URI, auth=MlflowAuth(), ca_bundle=BUNDLE)

        assert trusted, "the startup check built a client"
        assert all(issuers(verify) == [CA] for verify in trusted)
        resolved = str(Path(BUNDLE).resolve())
        assert os.environ["MLFLOW_TRACKING_SERVER_CERT_PATH"] == resolved
        assert get_default_host_creds(URI).server_cert_path == resolved

    def test_the_token_exchange_trusts_the_bundle(self, trusted):
        """Example 1, for `oidc`: the identity provider is behind the same CA."""
        auth = MlflowAuth(
            mode="oidc", token_url=TOKEN_URL, client_id="dossier-ci", client_secret="s"
        )

        adapter.connect(URI, auth=auth, ca_bundle=BUNDLE)

        assert len(trusted) >= 2, "the token exchange and the startup check"
        assert all(issuers(verify) == [CA] for verify in trusted)

    def test_an_untrusted_certificate_names_the_setting_that_trusts_one(self, monkeypatch):
        """Example 2: the one with no bundle, and a server the system store does not know."""

        def unverified(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                "unable to get local issuer certificate (_ssl.c:1028)",
                request=request,
            )

        monkeypatch.setattr(adapter, "HEALTH_TRANSPORT", httpx.MockTransport(unverified))

        with pytest.raises(adapter.TrackingUnavailable) as refused:
            adapter.connect(URI, auth=MlflowAuth())

        message = str(refused.value)
        assert URI in message
        assert "certificate verify failed" in message
        assert "DOSSIER_MLFLOW_CA_BUNDLE" in message

    def test_a_bundle_that_is_not_there_is_refused_before_any_request(self, trusted):
        """Example 3: the one with `certs/missing.crt`."""
        with pytest.raises(adapter.TrackingUnavailable) as refused:
            adapter.connect(URI, auth=MlflowAuth(), ca_bundle="certs/missing.crt")

        assert "DOSSIER_MLFLOW_CA_BUNDLE" in str(refused.value)
        assert "certs/missing.crt" in str(refused.value)
        assert trusted == [], "no request was made"

    def test_a_server_without_tls_reads_no_bundle(self):
        """Counter-example 4: the one with `http://localhost:5000`."""
        adapter.connect(
            "http://localhost:5000", auth=MlflowAuth(), ca_bundle="certs/missing.crt"
        )

        assert "MLFLOW_TRACKING_SERVER_CERT_PATH" not in os.environ
