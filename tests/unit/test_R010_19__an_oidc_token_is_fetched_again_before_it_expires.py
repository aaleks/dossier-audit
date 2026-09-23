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
