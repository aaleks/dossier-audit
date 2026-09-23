"""R10.22 — the first record a server refuses is reported as it is refused.

Two halves. What the warning says is a pure decision over the credential, the
status and the experiment (`refused_record`). When it is said is
`BestEffortTracker`'s: the first time a swallowed failure is a 401 or a 403,
once, and never for a server that has merely gone away.

MLflow's exception is recognised by what it answers to -- `get_http_status_code`
-- so the wrapper imports nothing from MLflow. What MLflow raises was read off a
live server: `PERMISSION_DENIED` is 403, `UNAUTHENTICATED` 401.
"""

from __future__ import annotations

import pytest
from tests.fakes import FakeTracker

from dossier.domain.tracking import MlflowAuth, refused_record
from dossier.infrastructure.tracking.best_effort import BestEffortTracker

pytest.importorskip("mlflow")

RUN = "dossier-audit/incident-audit/run"
PASSWORD = "correct-horse-battery-staple"
BASIC = MlflowAuth(mode="basic", username="dossier-ci", password=PASSWORD)


def mlflow_refuses(error_code: str):
    """MLflow's own exception, carrying the proto code it raises with -- not the string.

    `MlflowException(error_code="PERMISSION_DENIED")` answers 500, which is how
    this test's first draft passed a 403 off as a server error.
    """
    from mlflow.exceptions import MlflowException
    from mlflow.protos import databricks_pb2

    return MlflowException("API request failed", error_code=getattr(databricks_pb2, error_code))


class Answering(FakeTracker):
    """Raises `error` on every write, from the call after `after`."""

    def __init__(self, error: Exception, after: int = 0) -> None:
        super().__init__()
        self.error = error
        self.after = after

    def _maybe(self) -> None:
        if self.after <= 0:
            raise self.error
        self.after -= 1

    def start_run(self, **kwargs):
        self._maybe()
        return super().start_run(**kwargs)

    def log_params(self, params):
        self._maybe()
        return super().log_params(params)

    def end_run(self, *, status):
        self._maybe()
        return super().end_run(status=status)


def recorded(tracker: BestEffortTracker) -> None:
    tracker.start_run(experiment=RUN, name="20260806T142203Z-4f1a", tags={})
    tracker.log_params({"dossier_version": "0.1.0"})
    tracker.log_params({"model": "anthropic:claude-sonnet-4-5-20250929"})
    tracker.end_run(status="FINISHED")


class TestWhatTheWarningSays:
    """R10.22 — the status, the experiment, the variable; never the value."""

    def test_a_403_names_the_account_and_the_experiment_it_may_not_write_to(self):
        """Example 1's words, for `basic`."""
        said = refused_record(BASIC, status=403, experiment=RUN)

        assert "403 Forbidden" in said
        assert "DOSSIER_MLFLOW_AUTH_USERNAME" in said
        assert RUN in said
        assert PASSWORD not in said

    @pytest.mark.parametrize(
        ("auth", "named"),
        [
            (MlflowAuth(mode="bearer", token="mlf-token-2b9c"), "DOSSIER_MLFLOW_AUTH_TOKEN"),
            (
                MlflowAuth(
                    mode="oidc",
                    token_url="https://sso.example.internal/realms/dossier/protocol/openid-connect/token",
                    client_id="dossier-ci",
                    client_secret="client-secret-7f3a",
                ),
                "DOSSIER_MLFLOW_OIDC_CLIENT_ID",
            ),
            (MlflowAuth(), "DOSSIER_MLFLOW_AUTH"),
        ],
        ids=["bearer", "oidc", "none"],
    )
    def test_every_mode_names_its_own_variable(self, auth, named):
        """Counter-example 5, in every mode: a variable named, no value shown."""
        said = refused_record(auth, status=403, experiment=RUN)

        assert named in said
        for secret in ("mlf-token-2b9c", "client-secret-7f3a", PASSWORD):
            assert secret not in said

    def test_a_401_says_the_credential_was_not_accepted(self):
        """A credential refused mid-run -- a password changed while a run was at work."""
        said = refused_record(BASIC, status=401, experiment=RUN)

        assert "401 Unauthorized" in said
        assert "DOSSIER_MLFLOW_AUTH_PASSWORD" in said


class TestWhenItIsSaid:
    """R10.22 — first refusal, once; a server gone away, never."""

    def test_the_first_refusal_is_said_as_it_happens(self):
        """Example 1: said at `start_run`, before anything after it."""
        said: list[str] = []
        tracker = BestEffortTracker(
            Answering(mlflow_refuses("PERMISSION_DENIED")), warn=said.append, auth=BASIC
        )

        tracker.start_run(experiment=RUN, name="r", tags={})

        assert len(said) == 1
        assert said[0].startswith("warning: MLflow refused a record (403 Forbidden)")

    def test_it_is_said_once_and_the_rest_are_counted(self):
        """Example 2: four refusals, one warning, and R10.21's count at the close."""
        said: list[str] = []
        tracker = BestEffortTracker(
            Answering(mlflow_refuses("PERMISSION_DENIED")), warn=said.append, auth=BASIC
        )

        recorded(tracker)

        assert [line.split(":")[1].strip() for line in said] == [
            "MLflow refused a record (403 Forbidden)",
            "4 record(s) could not be recorded",
        ]

    def test_a_refusal_after_records_landed_is_still_said(self):
        """A 401 mid-run -- the first record refused need not be the first record."""
        said: list[str] = []
        tracker = BestEffortTracker(
            Answering(mlflow_refuses("UNAUTHENTICATED"), after=2), warn=said.append, auth=BASIC
        )

        recorded(tracker)

        assert "401 Unauthorized" in said[0]

    @pytest.mark.parametrize(
        "gone",
        [
            ConnectionError("the MLflow server at http://localhost:5000 stopped answering"),
            "TEMPORARILY_UNAVAILABLE",
        ],
        ids=["stopped-answering", "503"],
    )
    def test_a_server_that_went_away_is_only_counted(self, gone):
        """Counter-example 4: a 503, or no answer, is nothing to fix from the terminal."""
        error = mlflow_refuses(gone) if isinstance(gone, str) else gone
        said: list[str] = []
        tracker = BestEffortTracker(Answering(error), warn=said.append, auth=BASIC)

        recorded(tracker)

        assert said == ["warning: 4 record(s) could not be recorded"]
