"""R10.2 — the experiment a record lands in is rendered from the template for its
command.

An experiment should hold runs that are comparable with one another: a sync's
fetch counts, a run's traces and an eval's per-field accuracy are not, and
neither are two evals over different gold sets. So each command kind renders its
own template, falling back to the shared one, and the placeholders a template
may use are exactly the ones spec 010 lists.

Pure: the environment arrives as a mapping.
"""

from __future__ import annotations

import pytest

from dossier.domain.tracking import experiment_name


class TestExperimentNamesComeFromATemplate:
    """R10.2 — the experiment is rendered from the template for its command."""

    def test_with_no_template_a_run_lands_in_the_default_layout(self):
        """Example 1: the one where `dossier run incident-audit` sets nothing."""
        assert (
            experiment_name(kind="run", pipeline="incident-audit", gold=None, environ={})
            == "dossier-audit/incident-audit/run"
        )

    def test_a_commands_own_template_wins_and_can_name_the_gold_set(self):
        """Example 2: the one splitting evals by gold set.

        The eval template wins over `DOSSIER_MLFLOW_EXPERIMENT`, and `{gold}` is
        the gold directory's name: `gold/incidents` gives `incidents`.
        """
        environ = {
            "DOSSIER_MLFLOW_EXPERIMENT": "dossier-audit",
            "DOSSIER_MLFLOW_EXPERIMENT_EVAL": "dossier-audit/{pipeline}/eval/{gold}",
        }

        name = experiment_name(
            kind="eval", pipeline="incident-audit", gold="gold/incidents", environ=environ
        )

        assert name == "dossier-audit/incident-audit/eval/incidents"

    def test_a_template_with_no_placeholder_is_one_experiment_for_every_command(self):
        """Example 3: the one where everything records to `dossier-audit`."""
        environ = {"DOSSIER_MLFLOW_EXPERIMENT": "dossier-audit"}

        names = {
            experiment_name(kind=kind, pipeline="incident-audit", gold=gold, environ=environ)
            for kind, gold in (
                ("sync", None),
                ("convert", None),
                ("run", None),
                ("eval", "gold/incidents"),
            )
        }

        assert names == {"dossier-audit"}

    def test_an_unknown_placeholder_is_refused_naming_the_ones_allowed(self):
        """Example 4: the one with `{source}`, which no command can fill."""
        with pytest.raises(ValueError) as error:
            experiment_name(
                kind="run",
                pipeline="incident-audit",
                gold=None,
                environ={"DOSSIER_MLFLOW_EXPERIMENT": "dossier-audit/{source}"},
            )

        message = str(error.value)
        assert "DOSSIER_MLFLOW_EXPERIMENT" in message
        for placeholder in ("{pipeline}", "{kind}", "{gold}"):
            assert placeholder in message

    def test_gold_in_the_template_a_sync_uses_is_refused(self):
        """Counter-example (row 5): the one where a sync would render `{gold}`.

        A sync reads no gold set, so there is nothing to put there. The shared
        template with `{gold}` in it needs an override for every other kind,
        which is what the per-kind variables are for.
        """
        with pytest.raises(ValueError) as error:
            experiment_name(
                kind="sync",
                pipeline="incident-audit",
                gold=None,
                environ={"DOSSIER_MLFLOW_EXPERIMENT": "dossier-audit/{pipeline}/{gold}"},
            )

        assert "{gold}" in str(error.value)
