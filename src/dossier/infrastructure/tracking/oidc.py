"""An OIDC access token for MLflow, fetched before any work and again before expiry (R10.19).

The client-credentials grant: a service account's id and secret exchanged at an
identity provider's token endpoint -- Keycloak's
`/realms/<realm>/protocol/openid-connect/token`, or Entra ID's, Okta's or
Auth0's -- for a bearer token that lives minutes. A `dossier run` over a real
corpus lives longer, so the token in hand is checked on every request MLflow
sends and fetched again once no more than the refresh margin remains
(`dossier.domain.tracking.token_due`). The secret is sent in the form body
(`client_secret_post`).

What the endpoint answers is read here and handed to nothing but the
`Authorization` header. No key, manifest or score can depend on it (R0.10).

MLflow's trace exporter sends from a thread of its own, so the token is held
under a lock: two requests due at once make one exchange, not two.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from dossier.domain.tracking import (
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_TOKEN_URL,
    MlflowAuth,
    token_due,
    token_expiry,
)

# How the exchange reaches the identity provider. `None` is a real connection; a
# test answers with an `httpx.MockTransport`, so no socket is opened (R0.10).
TOKEN_TRANSPORT: httpx.BaseTransport | None = None

# An identity provider answers a token request in milliseconds; ten seconds is
# long enough for one under load and short enough to be reported before anyone
# wonders why nothing happened.
TOKEN_TIMEOUT_SECONDS = 10.0


class TokenRefused(RuntimeError):
    """No access token: the identity provider refused the client, or could not be reached."""


def _now() -> datetime:
    return datetime.now(UTC)


class TokenSource:
    """The access token a request carries, exchanged when none is held or it is due."""

    def __init__(self, auth: MlflowAuth, *, clock: Callable[[], datetime] = _now) -> None:
        self._auth = auth
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: datetime | None = None

    def authorization(self) -> str:
        """`Bearer <token>`, exchanging for a new token first when the held one is due."""
        with self._lock:
            now = self._clock()
            due = token_due(
                expires_at=self._expires_at, now=now, margin_seconds=self._auth.refresh_seconds
            )
            if self._token is None or due:
                self._token, self._expires_at = self._exchange(now)
            return f"Bearer {self._token}"

    def _exchange(self, now: datetime) -> tuple[str, datetime | None]:
        """One client-credentials exchange. Its expiry is counted from when it was asked for."""
        form = {
            "grant_type": "client_credentials",
            "client_id": self._auth.client_id,
            "client_secret": self._auth.client_secret,
        }
        # Sent only when set: Entra ID wants a scope, Auth0 an audience, and
        # Keycloak neither (R10.19 row 5).
        if self._auth.scope:
            form["scope"] = self._auth.scope
        if self._auth.audience:
            form["audience"] = self._auth.audience
        url = self._auth.token_url
        try:
            with httpx.Client(transport=TOKEN_TRANSPORT, timeout=TOKEN_TIMEOUT_SECONDS) as http:
                answered = http.post(url, data=form)
        except httpx.HTTPError as error:
            raise TokenRefused(
                f"no identity provider answers at {url} ({error}), the token endpoint "
                f"{OIDC_TOKEN_URL} names."
            ) from None
        if not answered.is_success:
            # The provider's own error code -- `invalid_client` -- says which fix;
            # it holds nothing the client sent. The secret is named, never shown.
            code = _error_code(answered)
            raise TokenRefused(
                f"the identity provider at {url} answered {answered.status_code} "
                f"{answered.reason_phrase}{f' ({code})' if code else ''}: it did not "
                f"issue a token for the client in {OIDC_CLIENT_ID} and {OIDC_CLIENT_SECRET}."
            )
        body = answered.json()
        token = body.get("access_token")
        if not token:
            raise TokenRefused(f"the identity provider at {url} answered with no access_token.")
        expires_in = body.get("expires_in")
        return token, token_expiry(
            issued_at=now, expires_in=int(expires_in) if expires_in is not None else None
        )


def _error_code(answered: httpx.Response) -> str | None:
    try:
        code = answered.json().get("error")
    except ValueError:
        return None
    return code if isinstance(code, str) else None
