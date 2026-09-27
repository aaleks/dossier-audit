"""R3.16 — a step that reads a `per_group` step's output is `per_group` or
`aggregate`, and anything else is refused at load time.

A `per_group` step answers once per group, so its outputs are named for groups:
`extract/ACME-2024.json`. A `per_file` step reading them would be asked about
`ACME-2024/master.pdf` and handed either the group's answer, which is about three
documents, or none, which drops the evidence. Neither is right, and which one
happened would depend on how the run happened to look the answer up. So it is
refused from the configuration alone, before a document is fetched, as a
`per_part` step over text is (R3.12 row 5).
"""

from __future__ import annotations

import pytest

from dossier.domain.pipeline import PipelineConfig, StepConfig, validate_modes


def _pipeline(*steps: tuple[str, str, str | list[str]]) -> PipelineConfig:
    """A pipeline of `(id, mode, input)` steps, in order."""
    return PipelineConfig(
        name="contract-renewal",
        sources=["contracts"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(id=step, prompt=f"prompts/{step}.md", input=read, mode=mode)
            for step, mode, read in steps
        ],
    )


class TestOnlyAGroupOrAggregateStepReadsAGroupStep:
    """R3.16 — who may read a `per_group` step's output."""

    def test_a_group_step_may_read_a_group_step(self):
        """Row 1: the one where `verify` checks each contract's extraction."""
        validate_modes(
            _pipeline(
                ("extract", "per_group", "documents"),
                ("verify", "per_group", ["documents", "extract"]),
            )
        )

    def test_an_aggregate_step_may_read_a_group_step(self):
        """Row 2: the one where `report` reads every contract's answer."""
        validate_modes(
            _pipeline(
                ("extract", "per_group", "documents"),
                ("report", "aggregate", "extract"),
            )
        )

    def test_a_per_file_step_reading_a_group_step_is_refused(self):
        """Row 3: the one with no answer to hand each file.

        Refused naming both steps and both modes, so the message says which of
        the two to change.
        """
        with pytest.raises(ValueError) as refused:
            validate_modes(
                _pipeline(
                    ("extract", "per_group", "documents"),
                    ("verify", "per_file", ["documents", "extract"]),
                )
            )

        message = str(refused.value)
        for named in ("'verify'", "per_file", "'extract'", "per_group"):
            assert named in message, message

    def test_a_group_step_may_read_a_per_file_step(self):
        """Row 4, a counter-example: the one in the other direction.

        Extracted per file, then combined per contract: each group's call holds
        its members' answers, each under the member's key, as it holds each
        member's text. Nothing is lost, so nothing is refused.
        """
        validate_modes(
            _pipeline(
                ("extract", "per_file", "documents"),
                ("combine", "per_group", ["documents", "extract"]),
            )
        )

    @pytest.mark.parametrize("sugar", ["previous", "previous(2)"])
    def test_a_group_step_named_by_previous_is_refused_too(self, sugar: str):
        """Row 3 again: the one where the group step is named by position.

        `previous` is sugar for the steps before this one (R4.2), and a rule
        that looked only at ids would let the same mistake through spelled
        differently.
        """
        with pytest.raises(ValueError, match="R3.16"):
            validate_modes(
                _pipeline(
                    ("extract", "per_group", "documents"),
                    ("tidy", "per_group", "extract"),
                    ("verify", "per_file", sugar),
                )
            )
