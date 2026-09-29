"""R3.19 — a step that reads an `aggregate` step's output is refused at load
time, naming both.

An `aggregate` step answers once for every document, and its one artifact is
filed under the reserved key `*`. Every reader looks an earlier step's answers up
under a document's key or a group's, so a step reading an aggregate step was
handed nothing, whatever its mode: a `per_file` reader was never asked, and a
`per_group` or `aggregate` reader was asked about an empty input. Found by
`/verify` on 2026-09-29. Refused from the configuration alone, as R3.16 refuses
a `per_file` reader of a `per_group` step: `validate_modes` runs when the
pipeline loads, before a document is fetched.
"""

from __future__ import annotations

import pytest

from dossier.domain.pipeline import PipelineConfig, StepConfig, validate_modes


def _pipeline(*steps: tuple[str, str, str | list[str]]) -> PipelineConfig:
    """A pipeline of `(id, mode, input)` steps, in order."""
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-jira"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(id=step, prompt=f"prompts/{step}.md", input=read, mode=mode)
            for step, mode, read in steps
        ],
    )


class TestNoStepReadsAnAggregateStep:
    """R3.19 — an `aggregate` step's output is read by no later step."""

    def test_a_per_file_step_reading_the_report_is_refused(self):
        """Row 1: the one where a summary is asked per incident about the report.

        Refused naming both steps and both modes, so the message says which of
        the two to change.
        """
        with pytest.raises(ValueError) as refused:
            validate_modes(
                _pipeline(
                    ("extract", "per_file", "documents"),
                    ("report", "aggregate", "extract"),
                    ("summary", "per_file", "report"),
                )
            )

        message = str(refused.value)
        for named in ("'summary'", "per_file", "'report'", "aggregate", "R3.19"):
            assert named in message, message

    def test_a_second_aggregate_step_reading_the_report_is_refused(self):
        """Row 2: the one where the reader reads a set, and is handed nothing all the same."""
        with pytest.raises(ValueError, match="R3.19"):
            validate_modes(
                _pipeline(
                    ("extract", "per_file", "documents"),
                    ("report", "aggregate", "extract"),
                    ("summary", "aggregate", "report"),
                )
            )

    def test_the_report_named_by_previous_is_refused_too(self):
        """Row 3: the one where `previous` is `report` (R4.2).

        A rule that looked only at ids would let the same mistake through
        spelled by position.
        """
        with pytest.raises(ValueError, match="'report', which is mode: aggregate"):
            validate_modes(
                _pipeline(
                    ("extract", "per_file", "documents"),
                    ("report", "aggregate", "extract"),
                    ("summary", "per_group", "previous"),
                )
            )

    def test_a_report_that_is_the_last_step_is_accepted(self):
        """Row 4, a counter-example: the one every pipeline in the repository has."""
        validate_modes(
            _pipeline(
                ("extract", "per_file", "documents"),
                ("report", "aggregate", "extract"),
            )
        )
