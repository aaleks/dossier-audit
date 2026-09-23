"""Shared fixtures.

Two of these are autouse, and both encode a project rule rather than a
convenience: the default suite reaches no network (R0.1), and no test's result
depends on the developer's own environment (R1.8).
"""

from __future__ import annotations

import shutil
import socket
from pathlib import Path

import pytest

from .fakes import FakeModelClient, NoModelClient

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Anything that could steer a connector, a model client or a credential lookup.
DOSSIER_ENV_PREFIXES = ("DOSSIER_", "JIRA_", "CONFLUENCE_", "ANTHROPIC_", "MLFLOW_")


class NetworkAccessDuringTest(AssertionError):
    """A test opened a socket. In this project that is a finding, not a flake."""


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Block socket creation for the whole default suite.

    R0.1 says nothing right of the hash boundary touches the network. Rather than
    trusting that, the suite makes it impossible: a test that reaches out fails
    at the socket, naming itself.

    Tests marked `live` are exempt -- that marker exists precisely for the
    `evaluated` rules that cannot be checked without a real model, and it is
    excluded from the default run.
    """
    if request.node.get_closest_marker("live"):
        return

    def refuse(*args, **kwargs):
        raise NetworkAccessDuringTest(
            f"{request.node.nodeid} tried to open a socket. "
            "Use a fake, or mark the test `live` if it genuinely needs a service."
        )

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def clean_env(request, monkeypatch):
    """Remove dossier's environment variables from every test.

    Without this, a test that reads configuration passes or fails depending on
    the developer's own shell, which is the kind of failure that only ever
    appears on someone else's machine.

    Tests marked `live` keep the environment, as they keep their sockets: where
    a model is served is per machine and is read from the environment by design
    (R9.2), so stripping it would point every live run at the default endpoint
    and quietly measure something other than what the operator configured.
    """
    if request.node.get_closest_marker("live"):
        return

    import os

    for name in list(os.environ):
        if name.startswith(DOSSIER_ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def mlflow_auth_provider(monkeypatch):
    """dossier's request auth provider known to MLflow, and MLflow's selector restored.

    `connect` sets MLflow's own `MLFLOW_TRACKING_AUTH` and
    `MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT` (R10.17, R10.23). `clean_env` removes
    a variable that was set, and cannot undo one a test creates, so each test
    starts by recording them as absent and `monkeypatch` puts that back
    afterwards.

    MLflow finds the provider through package metadata, and a checkout whose
    venv was installed before the entry point existed has none -- which
    `connect` refuses, correctly, in production. The suite proves the entry
    point is declared (R10.17); it does not depend on how recently the venv was
    reinstalled.
    """
    import os

    for name in (
        "MLFLOW_TRACKING_AUTH",
        "MLFLOW_TRACKING_SERVER_CERT_PATH",
        "MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT",
    ):
        monkeypatch.setenv(name, os.environ.get(name, ""))
        monkeypatch.delenv(name)
    # The credential in force is process state, as MLflow's URI is (R10.9). Each
    # test starts with none, so an `oidc` token one test fetched is not what the
    # next one's requests carry.
    from dossier.infrastructure.tracking import auth

    monkeypatch.setattr(auth, "_authorization", lambda: None)
    monkeypatch.setattr(auth, "_configured", None)
    try:
        from mlflow.tracking.request_auth import registry
    except ImportError:
        return
    from dossier.infrastructure.tracking.auth import PROVIDER, DossierAuthProvider

    providers = registry._request_auth_provider_registry
    if not any(provider.get_name() == PROVIDER for provider in providers):
        monkeypatch.setattr(
            providers, "_registry", [*providers._registry, DossierAuthProvider()]
        )


@pytest.fixture
def fake_model():
    """A model client returning canned responses and counting calls."""
    return FakeModelClient()


@pytest.fixture
def no_model():
    """A model client that fails on any call, for the zero-call rules."""
    return NoModelClient()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """An isolated copy of `tests/fixtures/`, safe to sync into and mutate.

    Copied rather than used in place: a sync writes a ledger and a snapshot
    store, and a test that leaves those behind changes the result of the next
    one (R2.5 is a claim about a *second* run).
    """
    destination = tmp_path / "workspace"
    shutil.copytree(FIXTURES, destination)
    return destination


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
