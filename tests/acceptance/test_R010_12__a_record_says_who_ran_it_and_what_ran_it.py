"""R10.12 — dossier writes four `mlflow.*` tags, and no others.

Supersedes R10.3, whose counter-example said `mlflow.user` and
`mlflow.source.name` were "left as MLflow sets them". `MlflowClient.create_run`
reads `mlflow.user` out of the tags handed to it and defaults it to `unknown`,
and sets no source at all -- so on dossier's path they were left *empty* rather
than left alone, and Created by and Source have been blank on every record
dossier has ever written.

`mlflow.note.content`, the fourth, is proved in the unit test beside this one:
what a description *says* is R11.12, and where it is carried is this rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

URI = "http://localhost:5000"
TOKEN = "DOSSIER_JIRA_TOKEN"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def held(workspace: Path, monkeypatch) -> Path:
    """The four incidents synced, with tracking still off."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


@pytest.fixture
def tracker(monkeypatch) -> FakeTracker:
    """Tracking on, recording to a fake that keeps the tags it was handed."""
    import dossier.cli.bootstrap as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    return recorder


class TestARecordSaysWhoRanItAndWhatRanIt:
    """R10.12 — dossier writes four `mlflow.*` tags, and no others."""

    def test_a_run_says_which_command_made_it(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where Source stops being a dash.

        R10.3's rows 1 and 2 are unchanged and asserted here too: what dossier
        says about the *work* stays under `dossier.`, which is what that rule was
        protecting and what this one keeps.
        """
        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        written = tracker.runs[0].tags
        assert written["dossier.kind"] == "run"
        assert written["dossier.pipeline"] == PIPELINE
        assert written["mlflow.source.name"] == "dossier run"
        assert written["mlflow.source.type"] == "LOCAL"

    def test_the_user_is_the_one_dossier_was_told_about(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one MLflow's UI shows as Created by.

        Read where every per-machine value is read (R9.11). It is a name, not a
        credential -- and R10.7 is untouched, which the last test here asserts.
        """
        monkeypatch.setenv("DOSSIER_MLFLOW_USER", "a.aleks")

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].tags["mlflow.user"] == "a.aleks"

    def test_a_machine_that_names_nobody_records_what_mlflow_would_have(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 3: the one where nothing names a user at all.

        `unknown` is exactly what `MlflowClient.create_run` stores when no
        `mlflow.user` tag reaches it, so this path is no worse than the one
        before this rule -- and it is still a tag rather than an absence, so the
        column reads the same on every record.
        """
        for named in ("DOSSIER_MLFLOW_USER", "USERNAME", "USER", "LOGNAME"):
            monkeypatch.delenv(named, raising=False)

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].tags["mlflow.user"] == "unknown"

    def test_mlflows_own_bookkeeping_is_left_alone(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 5): the one where dossier stops at four.

        The name goes through `run_name` and MLflow's `run_name` argument
        (R10.10), never through a tag dossier writes; the other two are MLflow's
        records of a shape dossier does not use.
        """
        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        written = set(tracker.runs[0].tags)
        assert not written & {
            "mlflow.runName",
            "mlflow.parentRunId",
            "mlflow.log-model.history",
        }
        assert {tag for tag in written if tag.startswith("mlflow.")} <= {
            "mlflow.user",
            "mlflow.source.name",
            "mlflow.source.type",
            "mlflow.note.content",
        }

    def test_no_credential_reaches_a_tag_under_either_prefix(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 6): the one R10.7 already promised.

        Worth asserting again here rather than trusting it: this rule is the
        first to write a tag from the environment, which is where a credential
        also lives.
        """
        monkeypatch.setenv(TOKEN, "s3cr3t-value")

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert all("s3cr3t-value" not in value for value in tracker.runs[0].tags.values())
