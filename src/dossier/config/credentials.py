"""What a source is reached with (R1.8).

`sources.yaml` is committed to git, so it says which variable holds a credential
and never what the credential is. The value is read here, from the environment,
when a connector is actually used -- loading reaches nothing and needs no
credential (R3.8, R1.8 row 1).

The same shape as `dossier.config.endpoints`, for the same reason: R9.8 is this
promise for model endpoints, and a second way of holding a secret would be a
second way of leaking one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from dossier.config.load import TOKEN_ENV, USER_ENV, ConfigError


class CredentialUnset(ConfigError):
    """A source names a variable for its credential and the variable is not set."""


@dataclass(frozen=True)
class Credential:
    """One source's credential: the variable it came from, and its value.

    The value is left out of `repr`, as an endpoint's key is (R9.8): a credential
    ends up inside connectors, error messages and tracebacks, and `repr` is what
    a traceback prints. `variable` stays visible on purpose -- naming what to set
    is the useful half, and it is not a disclosure (R1.8 row 4).
    """

    variable: str
    value: str = field(repr=False)
    # The user the token is paired with under HTTP Basic, and where it came
    # from (R1.12). `None` for the usual case, a bearer token on its own. Out
    # of `repr` like the value: an email is not a secret, but a log line is
    # not the place to find out whose account a run used.
    user: str | None = field(default=None, repr=False)
    user_variable: str | None = None

    def __str__(self) -> str:
        # `str` as well as `repr`: an f-string in a log line calls this one, and
        # that is exactly the line a person pastes into a ticket.
        return f"<credential from {self.variable}>"


def credential_for(source, *, environ: Mapping[str, str] | None = None) -> Credential | None:
    """The credential `source` is reached with, or `None` if it names no variable.

    `None` rather than an error: a folder source has nothing to authenticate to,
    and most sources in a workspace are like it. A source that *does* name a
    variable and finds it unset is an error, and it is raised when the connector
    is built rather than at load time, so that `dossier plan` over a Jira source
    works on a machine that cannot reach Jira (R3.8).
    """
    variable = str(source.options.get(TOKEN_ENV, "") or "")
    if not variable:
        return None

    environ = os.environ if environ is None else environ
    user_variable = str(source.options.get(USER_ENV, "") or "") or None
    return Credential(
        variable=variable,
        value=_read(source, variable, environ, what="credential"),
        user=_read(source, user_variable, environ, what="user") if user_variable else None,
        user_variable=user_variable,
    )


def _read(source, variable: str, environ: Mapping[str, str], *, what: str) -> str:
    """The value at `variable`, or `CredentialUnset` naming it.

    An empty variable counts as unset, as it does for an endpoint: a blank
    credential is not one anybody meant, and sending it produces a 401 that
    names the wrong cause. `.env` is named because the environment read here
    is the one it fills (R1.8 row 5) -- with a `DOSSIER_` name, which is all
    `.env` yields (R9.11 row 4).
    """
    value = environ.get(variable)
    if not value:
        raise CredentialUnset(
            f"source {source.id!r} reads its {what} from {variable}, which is not set. "
            f"Set {variable} in the environment, or in `.env` under a DOSSIER_ name."
        )
    return value
