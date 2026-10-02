"""Where a model provider is reached (spec 009, R9.2).

Per machine, read from the environment, and part of no key. `model:` says what
answers and is committed; where it is served differs between a laptop and a GPU
server, so it is read here and never from `pipeline.yaml` -- and because it is in
no key, the two machines share one cache (R5.13 row 5).

This package is the only one that reads the environment (R1.8). A provider's
default endpoint is the provider's own to state, as its entry point does: a
table of defaults here would make every new provider an edit to the core (R1.7).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from dossier.config.load import ConfigError


class EndpointUnset(ConfigError):
    """A model is needed and nothing says where it is served."""


@dataclass(frozen=True)
class Endpoint:
    """Where one provider is reached, and what it is reached with.

    The key is left out of `repr`: an endpoint ends up in error messages and
    tracebacks, and a key must reach none of them (R9.8).
    """

    url: str
    api_key: str | None = field(default=None, repr=False)


def endpoint_for(
    provider: str, *, default_url: str | None, environ: Mapping[str, str] | None = None
) -> Endpoint:
    """Where `provider` is reached on this machine.

    `DOSSIER_<PROVIDER>_URL` if it is set, the provider's own default if it has
    one, and otherwise an error naming the variable -- raised when a model is
    first needed, not when a pipeline loads, since a run served entirely from
    cache reaches no model and needs no endpoint (R9.2 row 5).

    An empty variable counts as unset. `.env.example` ships them blank, and a
    blank URL is not an endpoint anyone meant.
    """
    environ = os.environ if environ is None else environ
    variable = _variable(provider, "URL")
    url = environ.get(variable) or default_url
    if not url:
        raise EndpointUnset(
            f"{variable} is not set, and provider {provider!r} has no default endpoint. "
            f"Set {variable} to where it is served on this machine."
        )
    return Endpoint(url=url, api_key=environ.get(_variable(provider, "API_KEY")) or None)


def _variable(provider: str, suffix: str) -> str:
    return f"DOSSIER_{provider.upper()}_{suffix}"


class IndexDsnUnset(ConfigError):
    """An index is to be written and nothing says where (R18.7)."""


def index_dsn(variable: str, *, index: str, environ: Mapping[str, str] | None = None) -> str:
    """The connection string of the index `index` writes to, from `variable` (spec 018).

    Read here, from the environment, and never written in `indexes/<name>.yaml`:
    it carries a password, and that file is committed (R1.8). An empty variable
    counts as unset, as a blank model URL does. The value is returned to be
    used, and is never put in a message.
    """
    environ = os.environ if environ is None else environ
    if not environ.get(variable):
        raise IndexDsnUnset(
            f"{variable} is not set: it holds the connection string of the index "
            f"{index} is written to. Set it on this machine, in the shell or in .env, "
            "such as postgresql://dossier:<password>@127.0.0.1:5435/dossier"
        )
    return environ[variable]
