"""R14.12 — one lookup per prompt, linked to the run and to the version it built.

`dossier run` already asks the registry which version carries each step's hash
(R14.7). The version the run built is made of the same prompts, so the same
answer is linked there too, rather than asked for a second time.
"""

from __future__ import annotations

from tests.fakes import FakePromptRegistry, FakeTracker

NAME = "incident-audit.extract"
RENDERED = "4be9c072" * 8
VERSION = "m-7444e9ae3dcb4eb781e8579c81e2271f"


def _published() -> FakePromptRegistry:
    registry = FakePromptRegistry()
    registry.publish(name=NAME, template="t", tags={"dossier.prompt_hash": RENDERED})
    return registry


def _tracker() -> FakeTracker:
    tracker = FakeTracker()
    tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})
    return tracker


class TestOneLookupLinksTheRunAndTheVersion:
    """R14.12 — the version a run built links the prompts the run found."""

    def test_a_found_prompt_is_linked_to_the_run_and_the_version(self):
        """Row 1: the one where the Models tab says what a version is made of."""
        from dossier.application.prompts import link_published

        registry, tracker = _published(), _tracker()

        link_published(tracker, registry, [(NAME, RENDERED)], version_id=VERSION)

        assert tracker.links == [(NAME, 1)]
        assert tracker.version_links == [(VERSION, NAME, 1)]
        assert registry.reads == [NAME], "asked once, for both"

    def test_no_version_links_nothing_to_one(self):
        """Counter-example (row 6): the one with no logged model to link to (R13.5)."""
        from dossier.application.prompts import link_published

        tracker = _tracker()

        link_published(tracker, _published(), [(NAME, RENDERED)], version_id=None)

        assert tracker.links == [(NAME, 1)]
        assert tracker.version_links == []
