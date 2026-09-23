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

from dossier.domain.tracking import MlflowAuth, authorization

# The name MLflow finds this provider by, when `MLFLOW_TRACKING_AUTH` names it.
PROVIDER = "dossier"

# The `Authorization` value in force, or `None` for no header at all. Process
# state, as MLflow's own tracking URI is (R10.9): the provider is instantiated by
# MLflow's registry, with no arguments, and is handed nothing by anyone.
_header: str | None = None


def configure(auth: MlflowAuth) -> None:
    """Make `auth` the credential every request to MLflow carries from now on (R10.17)."""
    from mlflow.environment_variables import MLFLOW_TRACKING_AUTH

    global _header
    _header = authorization(auth)
    MLFLOW_TRACKING_AUTH.set(PROVIDER)


def headers() -> dict[str, str]:
    """The headers dossier's own startup check sends: the same value MLflow's requests carry."""
    return {"Authorization": _header} if _header is not None else {}


class _Authorize:
    """A `requests` auth hook, applied after MLflow has set a request's own headers.

    MLflow puts a credential it found for itself -- `MLFLOW_TRACKING_TOKEN`, or a
    pair from the shell or `~/.mlflow/credentials` -- on a request before this
    runs. It is replaced, and in mode `none` removed: it was set for some server,
    and nothing says that server is this one.
    """

    def __call__(self, request):
        request.headers.pop("Authorization", None)
        if _header is not None:
            request.headers["Authorization"] = _header
        return request


class DossierAuthProvider:
    """The request auth provider MLflow loads from dossier's entry point."""

    def get_name(self) -> str:
        return PROVIDER

    def get_auth(self) -> _Authorize:
        return _Authorize()
