"""R10.19 — an OIDC access token is fetched again once no more than the refresh margin remains.

A Keycloak access token lives five minutes by default, and a `dossier run` over a
real corpus does not finish in five. A token fetched once would record the first
documents and be refused for every record after it. So whether the token in hand
is still good enough is decided per request, against a clock passed in as an
argument -- which is what lets the boundary be pinned to the second here.

Pure: `token_due` takes the expiry and the time, and `settings` takes a dict.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dossier.domain.tracking import settings, token_due, token_expiry

ISSUED = datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC)
TOKEN_URL = "https://sso.example.internal/realms/dossier/protocol/openid-connect/token"


def at(clock: str) -> datetime:
    """`09:04:29` on the fixtures' day, in UTC."""
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return ISSUED.replace(hour=hours, minute=minutes, second=seconds)


def oidc(**extra: str) -> dict[str, str]:
    return {
        "DOSSIER_MLFLOW_ENABLED": "true",
        "DOSSIER_MLFLOW_TRACKING_URI": "https://mlflow.example.internal",
        "DOSSIER_MLFLOW_AUTH": "oidc",
        "DOSSIER_MLFLOW_OIDC_TOKEN_URL": TOKEN_URL,
        "DOSSIER_MLFLOW_OIDC_CLIENT_ID": "dossier-ci",
        "DOSSIER_MLFLOW_OIDC_CLIENT_SECRET": "client-secret-7f3a",
        **extra,
    }


EXPIRES = token_expiry(issued_at=ISSUED, expires_in=300)


class TestWhenATokenIsDue:
    """R10.19 — due once no more than the margin remains."""

    def test_a_token_with_more_than_the_margin_left_is_kept(self):
        """Example 2: the one at `09:04:29`, thirty-one seconds from expiry."""
        assert token_due(expires_at=EXPIRES, now=at("09:04:29"), margin_seconds=30) is False

    def test_exactly_the_margin_left_is_due(self):
        """Example 3: the one at `09:04:30`, the row that pins *no more than*.

        Thirty seconds left is due. Were the comparison strict, a request sent at
        `09:04:30` would carry a token with thirty seconds to live, and one that
        took longer than that to reach the server would arrive expired.
        """
        assert token_due(expires_at=EXPIRES, now=at("09:04:30"), margin_seconds=30) is True

    def test_a_longer_margin_is_read_not_hard_coded(self):
        """Example 4: the one with `DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS=60`."""
        margin = settings(oidc(DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS="60")).auth.refresh_seconds

        assert token_due(expires_at=EXPIRES, now=at("09:03:59"), margin_seconds=margin) is False
        assert token_due(expires_at=EXPIRES, now=at("09:04:00"), margin_seconds=margin) is True

    def test_a_token_shorter_lived_than_the_margin_is_due_at_once(self):
        """Example 9: the one answered `expires_in: 20` under the default margin.

        A new token for every request: a margin longer than a token's life costs
        a token request, never a record.
        """
        short = token_expiry(issued_at=ISSUED, expires_in=20)

        assert token_due(expires_at=short, now=ISSUED, margin_seconds=30) is True

    def test_a_token_whose_lifetime_is_unknown_is_never_reused_on_a_guess(self):
        """Example 9, the other half: the one answered with no `expires_in` at all."""
        unknown = token_expiry(issued_at=ISSUED, expires_in=None)

        assert unknown is None
        assert token_due(expires_at=unknown, now=ISSUED, margin_seconds=30) is True

    def test_expiry_is_the_issue_time_plus_its_lifetime(self):
        """`expires_in: 300` at `09:00:00` is `09:05:00`."""
        assert ISSUED + timedelta(seconds=300) == EXPIRES


class TestTheRefreshMargin:
    """R10.19 — `DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS`, thirty unless set."""

    @pytest.mark.parametrize("given", [{}, {"DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS": ""}])
    def test_unset_or_empty_is_thirty_seconds(self, given):
        """The default the user chose, and `.env.example` shows."""
        assert settings(oidc(**given)).auth.refresh_seconds == 30

    @pytest.mark.parametrize("value", ["soon", "-5", "2.5"])
    def test_a_value_that_is_not_a_whole_number_of_seconds_is_refused(self, value):
        """Example 8: the one with `soon`, or `-5`."""
        with pytest.raises(ValueError, match="DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS"):
            settings(oidc(DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS=value))

    def test_a_margin_for_a_mode_nobody_chose_chooses_nothing(self):
        """Counter-example 11's shape: `basic` reads no OIDC variable, a bad one included."""
        found = settings(
            {
                "DOSSIER_MLFLOW_ENABLED": "true",
                "DOSSIER_MLFLOW_TRACKING_URI": "https://mlflow.example.internal",
                "DOSSIER_MLFLOW_AUTH": "basic",
                "DOSSIER_MLFLOW_AUTH_USERNAME": "dossier-ci",
                "DOSSIER_MLFLOW_AUTH_PASSWORD": "correct-horse-battery-staple",
                "DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS": "soon",
            }
        )

        assert found.auth.mode == "basic"


class Clock:
    """A clock a test moves by hand."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Realm:
    """Keycloak's token endpoint: counts exchanges, and can stop answering."""

    def __init__(self, *, expires_in: int | None = 300) -> None:
        self.expires_in = expires_in
        self.forms: list[dict[str, list[str]]] = []
        self.down = False

    def __call__(self, request):
        import httpx

        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        from urllib.parse import parse_qs

        self.forms.append(parse_qs(request.content.decode()))
        body = {"access_token": f"token-{len(self.forms)}", "token_type": "Bearer"}
        if self.expires_in is not None:
            body["expires_in"] = self.expires_in
        return httpx.Response(200, json=body)


@pytest.fixture
def realm(monkeypatch) -> Realm:
    import httpx

    from dossier.infrastructure.tracking import oidc

    answering = Realm()
    monkeypatch.setattr(oidc, "TOKEN_TRANSPORT", httpx.MockTransport(answering))
    return answering


def source_for(realm: Realm, clock: Clock, **extra: str):
    from dossier.infrastructure.tracking.oidc import TokenSource

    return TokenSource(settings(oidc(**extra)).auth, clock=clock)


class TestTheExchange:
    """R10.19 — one exchange when due, and none when not."""

    def test_the_first_request_exchanges_once_with_the_grant_and_the_client(self, realm):
        """Example 1: the one at `09:00:00`, whose form holds nothing but these three."""
        clock = Clock(ISSUED)

        assert source_for(realm, clock).authorization() == "Bearer token-1"
        assert realm.forms == [
            {
                "grant_type": ["client_credentials"],
                "client_id": ["dossier-ci"],
                "client_secret": ["client-secret-7f3a"],
            }
        ]

    def test_a_token_is_kept_until_the_margin_and_fetched_again_at_it(self, realm):
        """Examples 2 and 3: `09:04:29` keeps token-1, `09:04:30` fetches token-2."""
        clock = Clock(ISSUED)
        source = source_for(realm, clock)
        source.authorization()

        clock.now = at("09:04:29")
        assert source.authorization() == "Bearer token-1"
        assert len(realm.forms) == 1

        clock.now = at("09:04:30")
        assert source.authorization() == "Bearer token-2"
        assert len(realm.forms) == 2

    def test_a_scope_and_an_audience_are_sent_when_set(self, realm):
        """Example 5: the one for Entra ID's scope and Auth0's audience."""
        source_for(
            realm,
            Clock(ISSUED),
            DOSSIER_MLFLOW_OIDC_SCOPE="mlflow",
            DOSSIER_MLFLOW_OIDC_AUDIENCE="https://mlflow.example.internal",
        ).authorization()

        assert realm.forms[0]["scope"] == ["mlflow"]
        assert realm.forms[0]["audience"] == ["https://mlflow.example.internal"]

    def test_a_token_whose_lifetime_nobody_stated_is_fetched_for_every_request(self, realm):
        """Example 9: the one answered with no `expires_in` -- never reused on a guess."""
        realm.expires_in = None
        source = source_for(realm, Clock(ISSUED))

        source.authorization()
        source.authorization()

        assert len(realm.forms) == 2

    def test_a_refresh_that_fails_mid_run_loses_the_record_not_the_run(self, realm):
        """Counter-example 10: the one where Keycloak stops answering at `09:04:30`.

        The request MLflow was about to send raises in its auth hook, so it is
        not sent without a credential. `BestEffortTracker` counts it as a lost
        record and the run goes on (R10.6).
        """
        from dossier.infrastructure.tracking import auth
        from dossier.infrastructure.tracking.best_effort import BestEffortTracker
        from dossier.infrastructure.tracking.oidc import TokenRefused

        clock = Clock(ISSUED)
        source = source_for(realm, clock)
        source.authorization()
        auth._authorization = source.authorization
        realm.down = True
        clock.now = at("09:04:30")

        class Request:
            headers: dict[str, str] = {}

        with pytest.raises(TokenRefused):
            auth.DossierAuthProvider().get_auth()(Request())

        class Recording:
            def start_run(self, **_):
                auth.DossierAuthProvider().get_auth()(Request())

        tracker = BestEffortTracker(Recording())
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})

    @pytest.mark.parametrize(
        "mode",
        [
            {
                "DOSSIER_MLFLOW_AUTH": "basic",
                "DOSSIER_MLFLOW_AUTH_USERNAME": "dossier-ci",
                "DOSSIER_MLFLOW_AUTH_PASSWORD": "correct-horse-battery-staple",
            },
            {"DOSSIER_MLFLOW_AUTH": "bearer", "DOSSIER_MLFLOW_AUTH_TOKEN": "mlf-token-2b9c"},
        ],
        ids=["basic", "bearer"],
    )
    def test_basic_and_bearer_make_no_exchange(self, realm, monkeypatch, mode):
        """Counter-example 11: the one where no identity provider is involved."""
        import httpx

        from dossier.infrastructure.tracking import mlflow as adapter

        monkeypatch.setattr(
            adapter, "HEALTH_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(200))
        )
        import mlflow

        monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
        found = settings(
            {
                "DOSSIER_MLFLOW_ENABLED": "true",
                "DOSSIER_MLFLOW_TRACKING_URI": "https://mlflow.example.internal",
                **mode,
            }
        )

        adapter.connect(found.uri, auth=found.auth)

        assert realm.forms == []
