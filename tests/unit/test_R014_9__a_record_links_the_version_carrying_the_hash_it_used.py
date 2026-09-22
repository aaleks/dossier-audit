"""R14.9 — a record links the version carrying the hash it used, and nothing else.

The use case R14.7 wrote inline in `dossier run`, now shared by the two commands
a judge runs under. Given the (name, hash) pairs `rubric_links` decided, it asks
the registry for each and links what it finds.
"""

from __future__ import annotations

from tests.fakes import FakePromptRegistry, FakeTracker

NAME = "incident-audit.judge.root_cause"
FIRST = "f7a2d9c4" * 8
DRAFT = "35d1a8ef" * 8


def _published(*hashes: str) -> FakePromptRegistry:
    registry = FakePromptRegistry()
    for held in hashes:
        registry.publish(name=NAME, template=held, tags={"dossier.prompt_hash": held})
    return registry


class TestARecordLinksTheVersionCarryingTheHashItUsed:
    """R14.9 — the version found by hash is linked; a hash nobody published links nothing."""

    def test_the_version_carrying_the_hash_is_linked_not_the_newest(self):
        """Row 1: the one where a draft was published over the words that were used."""
        from dossier.application.prompts import link_published

        tracker = FakeTracker()

        link_published(tracker, _published(FIRST, DRAFT), [(NAME, FIRST)])

        assert tracker.links == [(NAME, 1)]

    def test_a_hash_nobody_published_links_nothing(self):
        """Counter-example (row 6): the one where the registry has never seen these words."""
        from dossier.application.prompts import link_published

        tracker = FakeTracker()

        link_published(tracker, FakePromptRegistry(), [(NAME, FIRST)])

        assert tracker.links == []

    def test_a_registry_that_fails_costs_the_links_and_raises_nothing(self):
        """Counter-example: the one where the server is unwell (R10.4, R13.5).

        The first failure stops the lookups rather than repeating one per name
        against a server that has already refused, and the command goes on.
        """
        from dossier.application.prompts import link_published

        class Unwell(FakePromptRegistry):
            def find(self, name: str, prompt_hash: str):
                self.reads.append(name)
                raise ConnectionError("registry down")

        registry, tracker = Unwell(), FakeTracker()

        link_published(tracker, registry, [(NAME, FIRST), ("incident-audit.extract", DRAFT)])

        assert tracker.links == []
        assert registry.reads == [NAME], "one refusal, not one per name"
