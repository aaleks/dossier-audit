"""dossier's credential, on every request MLflow sends (R10.17).

MLflow resolves a credential per request, and asks the request auth providers
registered under the `mlflow.request_auth_provider` entry point for one when
`MLFLOW_TRACKING_AUTH` names them. `DossierAuthProvider` is that provider. It is
the one path every request takes -- a run's records, the traces MLflow's
asynchronous exporter sends from a thread of its own, the dataset, model and
prompt registries -- so one credential reaches all of them, where a variable
MLflow reads for itself would reach whichever paths happen to read it.

The secret stays in this process. What `configure` hands MLflow's own setting,
`MLFLOW_TRACKING_AUTH`, is the provider's *name*, which a subprocess may inherit
and learn nothing from. It is set through MLflow's API, as the tracking URI is
(R10.9): this configures the library dossier records with, and reads nothing.
`dossier.config` remains the only reader of the environment (R1.8, R9.11).

No `mlflow` import at module level. MLflow loads this module from its own
registry at its own import, and duck typing is all the registry asks of a
provider -- `get_name` and `get_auth` -- so a machine without the `tracking`
extra can still import it.
"""

from __future__ import annotations

from collections.abc import Callable

from dossier.domain.tracking import MlflowAuth, authorization

# The name MLflow finds this provider by, when `MLFLOW_TRACKING_AUTH` names it.
PROVIDER = "dossier"

# Where each request's `Authorization` value comes from, and the credential it was
# configured with. Process state, as MLflow's own tracking URI is (R10.9): the
# provider is instantiated by MLflow's registry, with no arguments, and is handed
# nothing by anyone. A callable rather than a value, because an `oidc` token is
# fetched again mid-run (R10.19); for `basic`, `bearer` and `none` it returns
# the one value settings decided.
_authorization: Callable[[], str | None] = lambda: None  # noqa: E731
_configured: MlflowAuth | None = None


def configure(auth: MlflowAuth, *, token: Callable[[], str] | None = None) -> None:
    """Make `auth` the credential every request to MLflow carries from now on (R10.17).

    `token` is where an `oidc` header comes from -- a `TokenSource` that has
    already made its first exchange (R10.19).
    """
    from mlflow.environment_variables import MLFLOW_TRACKING_AUTH

    global _authorization, _configured
    if auth.mode == "oidc":
        if token is None:
            raise ValueError("an `oidc` credential is configured with the token it carries")
        _authorization = token
    else:
        value = authorization(auth)
        _authorization = lambda: value  # noqa: E731
    _configured = auth
    MLFLOW_TRACKING_AUTH.set(PROVIDER)


def configured(auth: MlflowAuth) -> bool:
    """Whether `auth` is already the credential in force.

    A run connects its tracker and then its prompt registry to one server
    (R14.7). Configuring the same credential twice would make a second `oidc`
    exchange for a token already held.
    """
    return _configured == auth


def headers() -> dict[str, str]:
    """The headers dossier's own startup check sends: the same value MLflow's requests carry."""
    value = _authorization()
    return {"Authorization": value} if value is not None else {}


class _Authorize:
    """A `requests` auth hook, applied after MLflow has set a request's own headers.

    MLflow puts a credential it found for itself -- `MLFLOW_TRACKING_TOKEN`, or a
    pair from the shell or `~/.mlflow/credentials` -- on a request before this
    runs. It is replaced, and in mode `none` removed: it was set for some server,
    and nothing says that server is this one.
    """

    def __call__(self, request):
        # An `oidc` token due mid-run is fetched here, on MLflow's own thread. If
        # the identity provider is gone, this raises, the request is not sent,
        # and the record is lost and counted rather than the run (R10.6).
        value = _authorization()
        request.headers.pop("Authorization", None)
        if value is not None:
            request.headers["Authorization"] = value
        return request


class DossierAuthProvider:
    """The request auth provider MLflow loads from dossier's entry point."""

    def get_name(self) -> str:
        return PROVIDER

    def get_auth(self) -> _Authorize:
        return _Authorize()
