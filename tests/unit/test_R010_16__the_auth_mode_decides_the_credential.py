"""R10.16 — `DOSSIER_MLFLOW_AUTH` decides which credential dossier sends.

From that mode's variables alone.

The mode is chosen, never inferred from which variables happen to be set: a
guess that picked the wrong one would be found only after the run it should
have recorded, the reason `DOSSIER_MLFLOW_ENABLED` refuses a typo (R10.1).

Pure: the environment arrives as a mapping, so every row is a dict.
"""

from __future__ import annotations

import pytest

from dossier.domain.tracking import MlflowAuth, settings

URI = "https://mlflow.example.internal"
TOKEN_URL = "https://sso.example.internal/realms/dossier/protocol/openid-connect/token"
PASSWORD = "correct-horse-battery-staple"
SECRET = "client-secret-7f3a"


def env(**values: str) -> dict[str, str]:
    """Tracking switched on at the authenticated server, plus `values`."""
    return {
        "DOSSIER_MLFLOW_ENABLED": "true",
        "DOSSIER_MLFLOW_TRACKING_URI": URI,
        **{f"DOSSIER_MLFLOW_{key}": value for key, value in values.items()},
    }


class TestTheAuthModeDecidesTheCredential:
    """R10.16 — `DOSSIER_MLFLOW_AUTH` decides which credential dossier sends."""

    @pytest.mark.parametrize("given", [{}, {"AUTH": "none"}, {"AUTH": ""}])
    def test_unset_or_none_sends_no_credential(self, given):
        """Example 1: the one where nobody asked for a credential."""
        assert settings(env(**given)).auth == MlflowAuth(mode="none")

    def test_basic_sends_the_username_and_password(self):
        """Example 2: the one with MLflow's own basic auth."""
        found = settings(env(AUTH="basic", AUTH_USERNAME="dossier-ci", AUTH_PASSWORD=PASSWORD))

        assert found.auth == MlflowAuth(mode="basic", username="dossier-ci", password=PASSWORD)

    def test_bearer_sends_the_token_as_given(self):
        """Example 3: the one with a token a gateway issued."""
        found = settings(env(AUTH="bearer", AUTH_TOKEN="mlf-token-2b9c"))

        assert found.auth == MlflowAuth(mode="bearer", token="mlf-token-2b9c")

    def test_oidc_names_the_client_it_exchanges(self):
        """Example 4: the one with a Keycloak service account."""
        found = settings(
            env(
                AUTH="oidc",
                OIDC_TOKEN_URL=TOKEN_URL,
                OIDC_CLIENT_ID="dossier-ci",
                OIDC_CLIENT_SECRET=SECRET,
            )
        )

        assert found.auth == MlflowAuth(
            mode="oidc", token_url=TOKEN_URL, client_id="dossier-ci", client_secret=SECRET
        )

    def test_oidc_carries_a_scope_and_an_audience_when_set(self):
        """Example 4, the optional half: sent with the exchange when set (R10.19 row 5)."""
        found = settings(
            env(
                AUTH="oidc",
                OIDC_TOKEN_URL=TOKEN_URL,
                OIDC_CLIENT_ID="dossier-ci",
                OIDC_CLIENT_SECRET=SECRET,
                OIDC_SCOPE="mlflow",
                OIDC_AUDIENCE=URI,
            )
        )

        assert (found.auth.scope, found.auth.audience) == ("mlflow", URI)

    def test_basic_without_a_password_is_refused_naming_it(self):
        """Example 5: the one with half a pair."""
        with pytest.raises(ValueError, match="DOSSIER_MLFLOW_AUTH_PASSWORD"):
            settings(env(AUTH="basic", AUTH_USERNAME="dossier-ci"))

    def test_an_empty_client_secret_is_unset(self):
        """Example 6: the one where `.env.example` shipped the variable blank."""
        with pytest.raises(ValueError, match="DOSSIER_MLFLOW_OIDC_CLIENT_SECRET"):
            settings(
                env(
                    AUTH="oidc",
                    OIDC_TOKEN_URL=TOKEN_URL,
                    OIDC_CLIENT_ID="dossier-ci",
                    OIDC_CLIENT_SECRET="",
                )
            )

    def test_an_unknown_mode_is_refused_naming_the_four_it_takes(self):
        """Example 7: the one with `DOSSIER_MLFLOW_AUTH=keycloak`."""
        with pytest.raises(ValueError) as refused:
            settings(env(AUTH="keycloak"))

        message = str(refused.value)
        assert "DOSSIER_MLFLOW_AUTH" in message
        for mode in ("none", "basic", "bearer", "oidc"):
            assert f"`{mode}`" in message

    def test_a_variable_for_a_mode_nobody_chose_chooses_nothing(self):
        """Counter-example 8: the one with a token and no mode."""
        assert settings(env(AUTH_TOKEN="mlf-token-2b9c")).auth == MlflowAuth(mode="none")

    def test_who_ran_it_is_never_a_login(self):
        """Counter-example 9: the one where `DOSSIER_MLFLOW_USER` is not a username (R10.12)."""
        with pytest.raises(ValueError, match="DOSSIER_MLFLOW_AUTH_USERNAME"):
            settings(env(AUTH="basic", USER="a.aleks", AUTH_PASSWORD=PASSWORD))

    def test_tracking_off_reads_no_credential(self):
        """Counter-example 10: the one where nothing records, so nothing is refused."""
        assert settings({"DOSSIER_MLFLOW_AUTH": "keycloak"}) is None

    def test_no_secret_is_in_the_repr(self):
        """Example 11: a refusal or a log line printing settings discloses nothing (R10.7)."""
        shown = repr(MlflowAuth(mode="basic", username="dossier-ci", password=PASSWORD)) + repr(
            MlflowAuth(mode="oidc", client_secret=SECRET, token="mlf-token-2b9c")
        )

        assert PASSWORD not in shown
        assert SECRET not in shown
        assert "mlf-token-2b9c" not in shown
        assert "dossier-ci" in shown
