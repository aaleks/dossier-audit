"""R10.3 — every record carries `dossier.kind` and `dossier.pipeline`, whichever
experiment it lands in.

A template with no placeholder puts every command's records in one experiment
(R10.2 row 3). The tags are what keep that layout filterable: a run and an eval
in the same experiment are told apart by `dossier.kind`, and two pipelines by
`dossier.pipeline`. dossier writes only under its own `dossier.` prefix, so it
never overwrites what MLflow records about itself.

Pure: the tags are decided here and handed to the tracker port.
"""

from __future__ import annotations

from dossier.domain.tracking import experiment_name, tags


class TestEveryRecordIsTaggedWithItsKindAndPipeline:
    """R10.3 — every record carries its kind and its pipeline."""

    def test_a_run_is_tagged_with_its_kind_and_pipeline(self):
        """Example 1: the one recorded by `dossier run incident-audit`."""
        assert tags(kind="run", pipeline="incident-audit") == {
            "dossier.kind": "run",
            "dossier.pipeline": "incident-audit",
        }

    def test_a_run_and_an_eval_in_one_experiment_are_told_apart_by_kind(self):
        """Example 2: the one where `DOSSIER_MLFLOW_EXPERIMENT=dossier-audit`."""
        environ = {"DOSSIER_MLFLOW_EXPERIMENT": "dossier-audit"}
        run_in = experiment_name(
            kind="run", pipeline="incident-audit", gold=None, environ=environ
        )
        eval_in = experiment_name(
            kind="eval", pipeline="incident-audit", gold="gold/incidents", environ=environ
        )

        assert run_in == eval_in == "dossier-audit"
        assert tags(kind="run", pipeline="incident-audit")["dossier.kind"] == "run"
        assert tags(kind="eval", pipeline="incident-audit")["dossier.kind"] == "eval"

    def test_dossier_writes_only_under_its_own_prefix(self):
        """Counter-example (row 3): the one with `mlflow.user` and `mlflow.source.name`.

        Left as MLflow sets them. A tag dossier wrote under `mlflow.` would
        overwrite what MLflow records about the run itself.
        """
        for kind in ("sync", "convert", "run", "eval"):
            written = tags(kind=kind, pipeline="incident-audit")
            assert all(name.startswith("dossier.") for name in written)
            assert not {"mlflow.user", "mlflow.source.name"} & set(written)
