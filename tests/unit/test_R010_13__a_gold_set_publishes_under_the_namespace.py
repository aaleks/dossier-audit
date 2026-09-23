"""R10.13 — the application half for datasets: `publish_gold` under a namespace.

The gold set is the person-written one in `tests/fixtures/gold/incidents/`,
copied into a fresh workspace by the `workspace` fixture. No answer here was
written by this file.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeDatasetRegistry

EXPERIMENT = "dossier-audit/incident-audit/eval/incidents"


def _publish(registry: FakeDatasetRegistry, gold: Path, **kwargs):
    from dossier.application.datasets import publish_gold

    return publish_gold(registry, gold=gold, experiment=EXPERIMENT, **kwargs)


class TestAGoldSetPublishesUnderTheNamespace:
    """R10.13 — a gold set's dataset carries the machine's namespace."""

    def test_a_namespaced_gold_set_publishes_as_a_namespaced_dataset(self, workspace: Path):
        """Row 2: the one where `gold/incidents` publishes as `sandbox.incidents`."""
        registry = FakeDatasetRegistry()

        published = _publish(registry, workspace / "gold" / "incidents", namespace="sandbox")

        assert list(registry.datasets) == ["sandbox.incidents"]
        assert published.name == "sandbox.incidents"
        assert registry.datasets["sandbox.incidents"].experiments == [EXPERIMENT]

    def test_the_same_gold_set_under_two_namespaces_is_two_datasets(self, workspace: Path):
        """Row 3: the one where two checkouts sharing a server keep two datasets."""
        registry = FakeDatasetRegistry()
        gold = workspace / "gold" / "incidents"

        _publish(registry, gold, namespace="sandbox")
        _publish(registry, gold)

        assert sorted(registry.datasets) == ["incidents", "sandbox.incidents"]
