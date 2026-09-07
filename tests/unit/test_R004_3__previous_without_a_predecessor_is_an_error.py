"""R4.3 — `previous` with nothing preceding it is an error.

The failure this prevents is quiet. Asked for two preceding steps when only one
exists, a list slice happily returns one; the pipeline then runs with an input
list its author never wrote, and nothing anywhere says so. An error at
resolution is the only place this is still cheap (R4.1).

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.pipeline import StepConfig
from dossier.domain.resolution import expand


def steps(**inputs: str | list[str]) -> list[StepConfig]:
    """Steps in declaration order, each reading what the caller says."""
    return [
        StepConfig(id=name, prompt="prompts/01_extract.md", input=value, mode="per_file")
        for name, value in inputs.items()
    ]


class TestPreviousNeedsAPredecessor:
    """R4.3 — reaching back further than the pipeline goes."""

    def test_the_first_step_has_nothing_before_it(self):
        """Example 1: the one where `extract` asks for a step that cannot exist."""
        with pytest.raises(ValueError) as error:
            expand(steps(extract="previous"))

        message = str(error.value)
        assert "extract" in message
        assert "no" in message.lower() and "preced" in message.lower()

    def test_reaching_back_further_than_the_pipeline_goes(self):
        """Example 2: the one where `previous(2)` has only one step behind it."""
        with pytest.raises(ValueError) as error:
            expand(steps(extract="documents", verify="previous(2)"))

        message = str(error.value)
        assert "verify" in message
        assert "2" in message and "1" in message, (
            "the error must say what was asked for and what was available; "
            "an off-by-one is unreadable without both numbers"
        )

    def test_reaching_back_exactly_as_far_as_it_goes_is_allowed(self):
        """Example 3: the one where the bound is exact, not off by one.

        The counter-example to the counter-example. A check written with `>=`
        instead of `>` passes every other row in this file and rejects the one
        pipeline shape people actually write.
        """
        resolved = expand(steps(extract="documents", verify="previous(1)"))

        assert resolved[1].inputs == ["extract"]

    def test_a_first_step_may_still_read_its_sources(self):
        """Counter-example (row 4): the one where `extract` reads `documents`.

        A first step is not forbidden from having inputs. It is forbidden from
        having a *predecessor*, and conflating the two would make every pipeline
        illegal at step one.
        """
        resolved = expand(steps(extract="documents"))

        assert resolved[0].inputs == ["documents"]

    def test_the_error_arrives_before_any_step_resolves(self):
        """The one where a late error is still a total one (R4.1).

        `report` is the broken step and it is declared last. Resolution must
        still yield nothing at all -- a caller that got two resolved steps and an
        exception would be holding a half-resolved pipeline, which R4.1 says is
        never a state the system can be in.
        """
        with pytest.raises(ValueError):
            expand(steps(extract="documents", verify="extract", report="previous(9)"))
