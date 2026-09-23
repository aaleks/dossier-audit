"""R14.12 — the port a version link goes through, and what a failed one costs.

A prompt is linked to a pipeline version through `Tracker.version_prompt`, a
send like `log_version_metrics`: it names the version by the id the version
registry returned and returns nothing (R0.10).

A live spike found MLflow raises RESOURCE_DOES_NOT_EXIST when the model is not
there, so the call goes through `BestEffortTracker` like every other record: a
link lost costs the link, never the run (R10.6, R13.5).
"""

from __future__ import annotations

from tests.fakes import FakeTracker

from dossier.infrastructure.tracking.best_effort import BestEffortTracker

VERSION = "m-7444e9ae3dcb4eb781e8579c81e2271f"
PROMPT = "incident-audit.extract"


class Refusing(FakeTracker):
    """A tracker whose server has no such model, as MLflow answers for one."""

    def version_prompt(self, *, version_id: str, name: str, version: int) -> None:
        raise RuntimeError(
            f"RESOURCE_DOES_NOT_EXIST: Could not find model with ID '{version_id}'"
        )


class TestAVersionLinkThatFailsCostsTheLinkOnly:
    """R14.12 — a version link is sent through the tracker, best-effort."""

    def test_a_version_link_is_passed_straight_through(self):
        """Row 1: the one where the server answers."""
        inner = FakeTracker()
        tracker = BestEffortTracker(inner)
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})

        tracker.version_prompt(version_id=VERSION, name=PROMPT, version=1)

        assert inner.version_links == [(VERSION, PROMPT, 1)]

    def test_a_version_the_server_cannot_find_raises_nothing(self):
        """Counter-example (row 6): the one that costs the link and never the run."""
        tracker = BestEffortTracker(Refusing())
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})

        tracker.version_prompt(version_id=VERSION, name=PROMPT, version=1)
