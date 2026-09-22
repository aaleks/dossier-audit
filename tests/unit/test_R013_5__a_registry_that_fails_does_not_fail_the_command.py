"""R13.5 - a registry that cannot be reached does not fail the command.

R10.6 makes this promise for the tracker. It has to be made separately for the
registry, and not because the code is similar: because this port **returns**.
A tracker that swallows an exception has nothing left to hand back, and a
registry that swallowed one and returned a half-built object would fail a line
later, somewhere with no idea what went wrong.

So a failure gives `None`, and the caller's `if registered is None` is the whole
of what it costs. The acceptance test beside this one proves a `dossier run`
survives it; this one proves the wrapper.
"""

from __future__ import annotations

import pytest

from dossier.domain.resolution import PinnedDocument, ResolvedPlan, ResolvedStep
from dossier.domain.versions import PublishedVersion, version_record
from dossier.infrastructure.tracking.best_effort import BestEffortVersionRegistry

EXPERIMENT = "dossier-audit/incident-audit/run"


def _plan() -> ResolvedPlan:
    return ResolvedPlan(
        pipeline="incident-audit",
        pipeline_hash="2f60a7d3",
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[ResolvedStep(id="extract", inputs=["documents"], prompt_hash="77c1b40a")],
        documents=[PinnedDocument(key="INC-4821", snapshot="a3f9c1e2")],
    )


class Down:
    """A registry that cannot reach its server, however it is asked."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def register(self, *, record, experiment: str) -> PublishedVersion:
        self.calls += 1
        raise self.error


class Working:
    """A registry that answers."""

    def __init__(self) -> None:
        self.calls = 0

    def register(self, *, record, experiment: str) -> PublishedVersion:
        self.calls += 1
        return PublishedVersion(
            version_id="m-4746b054b65f4891b78c065e65a472ff",
            name=record.name,
            pipeline_hash="2f60a7d3",
            created=True,
        )


class TestARegistryThatFailsDoesNotFailTheCommand:
    """R13.5 - the work completes, the gap is counted, nothing is raised."""

    @pytest.mark.parametrize(
        "error",
        [
            ConnectionError("no route to host"),
            RuntimeError("the store cannot hold a logged model"),
            ValueError("malformed response"),
        ],
        ids=["unreachable", "wrong-store", "bad-answer"],
    )
    def test_any_failure_answers_none_rather_than_raising(self, error: Exception):
        """Example 1: the one where the run has work to do regardless.

        Three errors rather than one, because the reasons a tracking server
        fails are not enumerable from here -- a store that cannot hold a logged
        model raises differently from a host that is down, and R13.5 is the
        promise that the run does not care which.
        """
        registry = BestEffortVersionRegistry(Down(error))

        assert registry.register(record=version_record(_plan()), experiment=EXPERIMENT) is None

    def test_the_gap_is_counted_so_the_command_can_say_so(self):
        """Example 2: the one where silence would be the wrong answer.

        Counted as `BestEffortTracker` counts a lost trace, and for the reason
        R10.6 gives: an empty Models tab should not read as a pipeline nobody
        ever ran.
        """
        registry = BestEffortVersionRegistry(Down(ConnectionError("down")))

        registry.register(record=version_record(_plan()), experiment=EXPERIMENT)
        registry.register(record=version_record(_plan()), experiment=EXPERIMENT)

        assert registry.lost_versions == 2

    def test_a_registry_that_answers_is_passed_straight_through(self):
        """The counter-case that keeps the wrapper honest.

        A wrapper that swallowed everything would pass the tests above while
        recording nothing at all, which is the failure mode `BestEffortTracker`
        is most at risk of and the reason this assertion exists.
        """
        inner = Working()
        registry = BestEffortVersionRegistry(inner)

        registered = registry.register(record=version_record(_plan()), experiment=EXPERIMENT)

        assert registered is not None
        assert registered.version_id == "m-4746b054b65f4891b78c065e65a472ff"
        assert registry.lost_versions == 0
        assert inner.calls == 1

    def test_nothing_is_retried(self):
        """The one where a slow failure would cost the run its time.

        Sent once. A retry here would put a tracking server on the critical path
        of a command that fetches, converts and asks a model -- and R13.5 row 5
        is the line: a registry is not on the path that produces answers.
        """
        inner = Down(ConnectionError("down"))
        registry = BestEffortVersionRegistry(inner)

        registry.register(record=version_record(_plan()), experiment=EXPERIMENT)

        assert inner.calls == 1
