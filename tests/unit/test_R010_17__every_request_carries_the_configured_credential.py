"""R10.17 — every request dossier makes to MLflow carries the credential R10.16 decided.

And no other.

MLflow resolves a credential per request, in `mlflow.utils.rest_utils.http_request`,
from host credentials every store builds the same way. A run is written through a
`RestStore`; a trace is exported by `TracingClient`, whose store is resolved from
the same registry; a prompt or a logged model goes through the model registry's
store. So the claim is proved in two halves: every one of those stores resolves
to dossier's request auth provider, and a request sent through that provider
carries dossier's header and no other.

Nothing here opens a socket. `requests` is answered at its adapter, and the
startup check at `HEALTH_TRANSPORT`.
"""

from __future__ import annotations

import base64
import json
import os
import tomllib
from pathlib import Path

import httpx
import pytest

from dossier.domain.tracking import MlflowAuth
from dossier.infrastructure.tracking import mlflow as adapter

URI = "https://mlflow.example.internal"
PASSWORD = "correct-horse-battery-staple"
TOKEN = "mlf-token-2b9c"
BASIC = "Basic " + base64.b64encode(f"dossier-ci:{PASSWORD}".encode()).decode()

pytest.importorskip("mlflow")


@pytest.fixture
def sent(monkeypatch) -> list:
    """Every request `requests` would have put on the wire, answered `{}` with a 200."""
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
    return prepared


@pytest.fixture
def checked(monkeypatch) -> list[httpx.Request]:
    """Every request the startup check made, each answered 200."""
    asked: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json={})

    monkeypatch.setattr(adapter, "HEALTH_TRANSPORT", httpx.MockTransport(answer))
    return asked


@pytest.fixture(autouse=True)
def mlflow_left_alone(monkeypatch):
    """Building a tracker points MLflow's process-wide URI; a test leaves it as it was."""
    import mlflow

    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)


def mlflow_sends(path: str = "/api/2.0/mlflow/runs/create") -> None:
    """One request down the funnel every MLflow store sends through."""
    from mlflow.utils.credentials import get_default_host_creds
    from mlflow.utils.rest_utils import http_request

    http_request(get_default_host_creds(URI), path, "POST", json={})


class TestEveryRequestCarriesTheConfiguredCredential:
    """R10.17 — one credential, on every path out to MLflow."""

    def test_basic_is_on_the_startup_check_and_on_what_mlflow_sends(self, sent, checked):
        """Example 1: the one where `dossier-ci` records a run.

        The header checked at startup is the header every record sends, because
        both come from one function.
        """
        adapter.connect(
            URI, auth=MlflowAuth(mode="basic", username="dossier-ci", password=PASSWORD)
        )

        mlflow_sends("/api/2.0/mlflow/runs/create")
        mlflow_sends("/api/2.0/mlflow/runs/log-batch")

        assert [request.headers["Authorization"] for request in checked] == [BASIC] * len(
            checked
        )
        assert [request.headers["Authorization"] for request in sent] == [BASIC, BASIC]

    def test_every_store_mlflow_builds_asks_dossier_for_the_credential(self, checked):
        """Example 1, the other paths: traces and the registries resolve the same provider.

        The trace exporter builds a `TracingClient` from the tracking URI, and a
        prompt or a logged model is written through the model registry's store.
        Were either to resolve its credential elsewhere, the run would record and
        its traces or its prompt links would be refused.
        """
        from mlflow.tracing.client import TracingClient
        from mlflow.tracking._model_registry.utils import _get_store as registry_store
        from mlflow.tracking._tracking_service.utils import _get_store as tracking_store

        adapter.connect(URI, auth=MlflowAuth(mode="bearer", token=TOKEN))

        stores = [tracking_store(URI), registry_store(URI), TracingClient(URI).store]
        assert [store.get_host_creds().auth for store in stores] == ["dossier"] * 3

    def test_bearer_is_what_the_registries_send(self, sent, checked):
        """Example 2: the one where `dossier prompts publish` sends its prompts."""
        adapter.connect_prompts(URI, auth=MlflowAuth(mode="bearer", token=TOKEN))

        mlflow_sends("/api/2.0/mlflow/registered-models/create")

        assert sent[0].headers["Authorization"] == f"Bearer {TOKEN}"
        assert {request.headers["Authorization"] for request in checked} == {f"Bearer {TOKEN}"}

    def test_mlflows_own_token_in_the_shell_decides_nothing(self, sent, checked, monkeypatch):
        """Example 3: the one with `MLFLOW_TRACKING_TOKEN` left in the shell."""
        monkeypatch.setenv("MLFLOW_TRACKING_TOKEN", "a-token-for-another-server")

        adapter.connect(
            URI, auth=MlflowAuth(mode="basic", username="dossier-ci", password=PASSWORD)
        )
        mlflow_sends()

        assert sent[0].headers["Authorization"] == BASIC

    def test_none_sends_no_header_even_when_the_shell_holds_one(
        self, sent, checked, monkeypatch
    ):
        """Example 4: the one where a pair left in the shell is not sent to this server."""
        monkeypatch.setenv("MLFLOW_TRACKING_USERNAME", "someone-else")
        monkeypatch.setenv("MLFLOW_TRACKING_PASSWORD", "their-password")

        adapter.connect(URI, auth=MlflowAuth())
        mlflow_sends()

        assert "Authorization" not in sent[0].headers
        assert all("Authorization" not in request.headers for request in checked)

    @pytest.mark.parametrize(
        "auth",
        [
            MlflowAuth(),
            MlflowAuth(mode="basic", username="dossier-ci", password=PASSWORD),
            MlflowAuth(mode="bearer", token=TOKEN),
        ],
        ids=["none", "basic", "bearer"],
    )
    def test_the_process_environment_holds_a_name_and_no_secret(self, auth, checked):
        """Example 5: the one where a subprocess inherits nothing worth stealing."""
        adapter.connect(URI, auth=auth)

        assert os.environ["MLFLOW_TRACKING_AUTH"] == "dossier"
        held = "\n".join(os.environ.values())
        assert PASSWORD not in held
        assert TOKEN not in held

    def test_a_provider_mlflow_cannot_find_is_refused_before_any_work(
        self, checked, monkeypatch
    ):
        """Example 8: the one with a stale install, whose metadata predates the entry point.

        MLflow would find no provider, send no credential, and every record would
        be refused while the startup check -- which takes its header from dossier
        directly -- passed.
        """
        from mlflow.tracking.request_auth import registry

        monkeypatch.setattr(registry._request_auth_provider_registry, "_registry", [])

        with pytest.raises(adapter.TrackingUnavailable, match="reinstall"):
            adapter.connect(URI, auth=MlflowAuth(mode="bearer", token=TOKEN))
        assert checked == []

    def test_the_provider_is_declared_where_mlflow_looks_for_it(self):
        """MLflow loads request auth providers from this entry point, at its own import."""
        pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())

        declared = pyproject["project"]["entry-points"]["mlflow.request_auth_provider"]
        assert declared == {
            "dossier": "dossier.infrastructure.tracking.auth:DossierAuthProvider"
        }

    def test_tracking_off_names_no_provider(self, monkeypatch):
        """Counter-example 7: the one where tracking is off.

        No tracker is built, so nothing is configured and MLflow's own variable is
        left exactly as it was (R10.9 row 4).
        """
        from dossier.domain.tracking import settings

        monkeypatch.setenv("MLFLOW_TRACKING_AUTH", "someone-elses-plugin")

        assert settings({"DOSSIER_MLFLOW_AUTH": "basic"}) is None
        assert os.environ["MLFLOW_TRACKING_AUTH"] == "someone-elses-plugin"


def test_a_request_body_is_left_as_mlflow_built_it(sent, checked):
    """The provider sets one header and touches nothing else a record carries."""
    adapter.connect(URI, auth=MlflowAuth(mode="bearer", token=TOKEN))

    from mlflow.utils.credentials import get_default_host_creds
    from mlflow.utils.rest_utils import http_request

    http_request(
        get_default_host_creds(URI), "/api/2.0/mlflow/runs/create", "POST", json={"a": 1}
    )

    assert json.loads(sent[0].body) == {"a": 1}
