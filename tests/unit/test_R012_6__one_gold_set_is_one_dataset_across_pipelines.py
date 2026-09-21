"""R012.6 — one gold set is one dataset, and a second pipeline publishing it adds
its experiment rather than a second dataset.

A gold set is a workspace asset and can serve several pipelines (R3.7), while
MLflow names a dataset globally. So the name follows the gold set and the pipeline
follows R10.2 into the list of experiments the one dataset belongs to.

`gold/observability` is copied from `gold/incidents` here under its own name: the
claim is about which *name* a dataset takes, not about which documents are in it,
and copying keeps every answer one a person actually verified.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tests.fakes import FakeDatasetRegistry

INCIDENT_AUDIT = "dossier-audit/incident-audit/eval/incidents"
POSTMORTEM_REVIEW = "dossier-audit/postmortem-review/eval/incidents"
# A template with no placeholder puts every record in one experiment (R10.2 row 3).
ONE_EXPERIMENT = "dossier-audit"


def _publish(registry: FakeDatasetRegistry, gold: Path, experiment: str):
    from dossier.application.datasets import publish_gold

    return publish_gold(registry, gold=gold, experiment=experiment)


class TestOneGoldSetIsOneDatasetAcrossPipelines:
    """R12.6 — one gold set is one dataset; a second pipeline adds its experiment."""

    def test_a_second_pipeline_adds_its_experiment_to_the_same_dataset(self, workspace: Path):
        """Example 1: the one where two pipelines are measured against one gold set.

        A second dataset would mean two names for one set of answers, and two
        places to look for the runs measured against them.
        """
        registry = FakeDatasetRegistry()
        gold = workspace / "gold" / "incidents"

        _publish(registry, gold, INCIDENT_AUDIT)
        second = _publish(registry, gold, POSTMORTEM_REVIEW)

        assert list(registry.datasets) == ["incidents"], "one gold set, one dataset"
        assert registry.created == ["incidents"], "created once, not twice"
        assert second.records == 4
        assert second.added == 0
        assert registry.datasets["incidents"].experiments == [
            INCIDENT_AUDIT,
            POSTMORTEM_REVIEW,
        ]

    def test_a_second_gold_set_is_a_second_dataset(self, workspace: Path):
        """Example 2: the one where the name follows the gold set, not the pipeline.

        The same pipeline measured against two gold sets publishes two datasets,
        because they are two different sets of answers.
        """
        registry = FakeDatasetRegistry()
        incidents = workspace / "gold" / "incidents"
        observability = workspace / "gold" / "observability"
        shutil.copytree(incidents, observability)

        _publish(registry, incidents, INCIDENT_AUDIT)
        _publish(registry, observability, "dossier-audit/incident-audit/eval/observability")

        assert sorted(registry.datasets) == ["incidents", "observability"]
        assert registry.created == ["incidents", "observability"]

    def test_a_template_that_collapses_two_experiments_lists_it_once(self, workspace: Path):
        """Counter-example (row 3): the one where both pipelines render one experiment.

        A template with no `{gold}` or `{pipeline}` in it puts every record in one
        experiment (R10.2 row 3). That is one experiment listed once, not two
        datasets and not the same experiment twice.
        """
        registry = FakeDatasetRegistry()
        gold = workspace / "gold" / "incidents"

        _publish(registry, gold, ONE_EXPERIMENT)
        _publish(registry, gold, ONE_EXPERIMENT)

        assert list(registry.datasets) == ["incidents"]
        assert registry.datasets["incidents"].experiments == [ONE_EXPERIMENT]
