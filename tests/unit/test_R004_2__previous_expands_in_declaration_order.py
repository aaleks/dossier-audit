"""R4.2 — `previous` expands to the preceding step id, `previous(n)` to the `n` preceding ids.

In declaration order, so that reading a manifest never requires reading the
pipeline it came from. That is the whole point of expanding at all: a manifest
found in `runs/` three years from now has to be readable on its own, and
`previous` is only meaningful next to the file it was written in.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.pipeline import StepConfig
from dossier.domain.resolution import expand


def steps(**inputs: str | list[str]) -> list[StepConfig]:
    """Steps in declaration order, each reading what the caller says.

    Keyword order is declaration order -- Python keeps it -- which keeps the
    call site reading like the YAML it stands for.
    """
    return [
        StepConfig(id=name, prompt="prompts/01_extract.md", input=value, mode="per_file")
        for name, value in inputs.items()
    ]


class TestPreviousExpansion:
    """R4.2 — after this, the word `previous` is gone."""

    def test_previous_is_the_step_before_it(self):
        """Example 1: the one where `report` reads `verify`."""
        resolved = expand(steps(extract="documents", verify="extract", report="previous"))

        assert resolved[2].inputs == ["verify"]

    def test_previous_n_is_the_n_steps_before_it(self):
        """Example 2: the one where `previous(2)` reaches back two, in order."""
        resolved = expand(steps(extract="documents", verify="extract", report="previous(2)"))

        assert resolved[2].inputs == ["extract", "verify"]

    def test_sugar_mixes_with_a_keyword(self):
        """Example 3: the one where `[documents, previous]` is allowed."""
        resolved = expand(steps(extract="documents", verify=["documents", "previous"]))

        assert resolved[1].inputs == ["documents", "extract"]

    def test_a_concrete_reference_is_left_alone(self):
        """Counter-example (row 4): the one where there is nothing to expand.

        The expander must be a no-op on a pipeline that never used the sugar,
        or every already-concrete pipeline would resolve to something subtly
        different from what its author wrote.
        """
        resolved = expand(steps(extract="documents", verify="extract", report="verify"))

        assert [step.inputs for step in resolved] == [["documents"], ["extract"], ["verify"]]

    def test_the_step_ids_survive_expansion(self):
        """The one where the ids are still there to be read.

        `expand` returns steps, not just input lists; a caller matching them back
        up by position would be one insertion away from a wrong manifest.
        """
        resolved = expand(steps(extract="documents", verify="previous"))

        assert [step.id for step in resolved] == ["extract", "verify"]

    @pytest.mark.parametrize("declared", ["previous", "previous(1)"])
    def test_previous_and_previous_1_mean_the_same_thing(self, declared: str):
        """The one where the sugar has no off-by-one.

        `previous` is `previous(1)`. Writing them as separate paths is how they
        drift apart.
        """
        resolved = expand(steps(extract="documents", verify=declared))

        assert resolved[1].inputs == ["extract"]
