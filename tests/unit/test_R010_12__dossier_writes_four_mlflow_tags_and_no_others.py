"""R10.12 — dossier writes four `mlflow.*` tags, and no others.

Reclaims R10.3's test. That rule's rows 1 and 2 -- every record carries
`dossier.kind` and `dossier.pipeline`, and two commands in one experiment are
told apart by them -- are asserted here unchanged, because they are still true
and still the thing worth protecting. Its row 3 is what changed: dossier does
now write under `mlflow.`, because on the path dossier records through MLflow
writes nothing there itself.

Pure. The environment arrives as a mapping, so the user a record names is
provable with a dict rather than with whoever ran the suite.
"""

from __future__ import annotations

from dossier.domain.tracking import MLFLOW_TAGS, experiment_name, tags, user_for

PIPELINE = "incident-audit"


class TestDossierWritesFourMLflowTagsAndNoOthers:
    """R10.12 — dossier writes four `mlflow.*` tags, and no others."""

    def test_a_run_says_its_kind_its_pipeline_and_which_command_made_it(self):
        """Example 1: R10.3's row 1, plus the source that was never there."""
        assert tags(
            kind="run", pipeline=PIPELINE, environ={"DOSSIER_MLFLOW_USER": "a.aleks"}
        ) == {
            "dossier.kind": "run",
            "dossier.pipeline": PIPELINE,
            "mlflow.user": "a.aleks",
            "mlflow.source.name": "dossier run",
            "mlflow.source.type": "LOCAL",
        }

    def test_a_run_and_an_eval_in_one_experiment_are_still_told_apart_by_kind(self):
        """R10.3's row 2, carried over: a shared experiment stays filterable."""
        environ = {"DOSSIER_MLFLOW_EXPERIMENT": "dossier-audit"}
        run_in = experiment_name(kind="run", pipeline=PIPELINE, gold=None, environ=environ)
        eval_in = experiment_name(
            kind="eval", pipeline=PIPELINE, gold="gold/incidents", environ=environ
        )

        assert run_in == eval_in == "dossier-audit"
        assert tags(kind="run", pipeline=PIPELINE, environ={})["dossier.kind"] == "run"
        assert tags(kind="eval", pipeline=PIPELINE, environ={})["dossier.kind"] == "eval"

    def test_the_user_dossier_was_told_about_wins(self):
        """Example 2: the one MLflow's UI shows as Created by."""
        assert user_for({"DOSSIER_MLFLOW_USER": "a.aleks", "USERNAME": "aleks"}) == "a.aleks"

    def test_the_account_the_command_ran_under_is_the_fallback(self):
        """Example 3, first half: the one nobody configured.

        Read from the same mapping every other per-machine value is read from
        (R9.11), so no part of `domain/` goes and asks the operating system.
        """
        assert user_for({"USERNAME": "aleks"}) == "aleks"
        assert user_for({"USER": "aleks"}) == "aleks"

    def test_a_machine_that_names_nobody_records_what_mlflow_would_have(self):
        """Example 3, second half: the one with no account variable at all.

        `unknown` is what `MlflowClient.create_run` stores when no `mlflow.user`
        tag reaches it, so this path is no worse than the one before this rule --
        and it is a value rather than an absence, so the column reads the same on
        every record.
        """
        assert user_for({}) == "unknown"

    def test_the_four_are_the_whole_list(self):
        """Counter-example (row 5): the one that keeps the list from growing.

        `mlflow.runName` is the trap: MLflow reads a run's name from that tag as
        well as from `create_run`'s argument, so writing it would be a second
        place a name comes from -- and R10.10 has exactly one.
        """
        assert MLFLOW_TAGS == (
            "mlflow.user",
            "mlflow.source.name",
            "mlflow.source.type",
            "mlflow.note.content",
        )
        written = tags(kind="run", pipeline=PIPELINE, environ={})
        assert {tag for tag in written if tag.startswith("mlflow.")} <= set(MLFLOW_TAGS)

    def test_a_credential_in_the_environment_reaches_no_tag(self):
        """Counter-example (row 6): R10.7's promise, asserted where it is newly at risk.

        This is the first rule that writes a tag *from* the environment, which is
        where a credential also lives. Only the variables named here are read.
        """
        written = tags(
            kind="run",
            pipeline=PIPELINE,
            environ={"DOSSIER_JIRA_TOKEN": "s3cr3t-value", "USERNAME": "aleks"},
        )

        assert all("s3cr3t-value" not in value for value in written.values())

    def test_a_description_is_carried_in_mlflow_note_content(self):
        """Example 4: the one that fills the box a person reads first.

        Where a description is carried is this rule; what it *says* is R11.12,
        which is why the text here is a stand-in. `mlflow.note.content` is the
        only tag MLflow's UI renders as Description, so there is no second place
        it could go.
        """
        from tests.fakes import FakeTracker

        recorder = FakeTracker()
        recorder.start_run(experiment="dossier-audit", name="eval", tags={})
        recorder.describe("overall 80.0% over 5 fields")

        assert recorder.runs[0].tags["mlflow.note.content"] == "overall 80.0% over 5 fields"
