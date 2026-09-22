"""R11.13 — a comparison names the steps that differ between the two runs.

The question a change gate is opened with is "what changed?", and the record
answered "these five numbers did". Which prompt moved, which model, which
documents -- the cause of the delta -- was in neither run's record.

`dossier run --plan` already computes exactly this over exactly these inputs
(R4.12). Nothing new decides anything here: `changed_steps` turns what `diff`
returns into the one line a tag can hold.
"""

from __future__ import annotations

from dossier.domain.plan import StepPlan, StepStatus, changed_steps
from dossier.domain.resolution import ResolvedStep


def _line(*statuses: tuple[str, StepStatus]) -> str:
    return changed_steps(
        [
            StepPlan(step=ResolvedStep(id=step, inputs=[]), status=status)
            for step, status in statuses
        ]
    )


class TestAComparisonNamesWhatDiffersBetweenItsRuns:
    """R11.13 — a comparison names the steps that differ between the two runs."""

    def test_a_changed_prompt_is_named_with_the_step_it_belongs_to(self):
        """Example 1: the one where the delta gets a stated cause."""
        assert _line(("extract", StepStatus.CACHED), ("verify", StepStatus.PROMPT_CHANGED)) == (
            "verify (prompt changed)"
        )

    def test_a_changed_model_names_every_step(self):
        """Example 2: the one where the pin belongs to the plan, not to a step (R4.12)."""
        assert (
            _line(
                ("extract", StepStatus.MODEL_CHANGED),
                ("verify", StepStatus.MODEL_CHANGED),
                ("report", StepStatus.MODEL_CHANGED),
            )
            == "extract (model changed), verify (model changed), report (model changed)"
        )

    def test_a_moved_document_names_the_step_that_reads_it_and_those_below(self):
        """Example 3: the one where the propagation R4.12 walks is visible.

        `extract` reads the document; `verify` re-runs because what it reads
        moved. Reporting only `extract` would leave someone wondering why
        `verify`'s score changed when nothing about `verify` did.
        """
        assert (
            _line(
                ("extract", StepStatus.DOCUMENTS_CHANGED),
                ("verify", StepStatus.UPSTREAM_CHANGED),
            )
            == "extract (documents changed), verify (upstream changed)"
        )

    def test_the_steps_are_named_in_declaration_order(self):
        """The order a person reads a pipeline in, which is the order `diff` walks.

        Nothing here enters a key (R10.4), so any order would break no rule --
        and a tag whose order moved between two comparisons of the same change
        would read as two different findings.
        """
        assert (
            _line(
                ("extract", StepStatus.PROMPT_CHANGED),
                ("verify", StepStatus.PROMPT_CHANGED),
            )
            == "extract (prompt changed), verify (prompt changed)"
        )

    def test_two_runs_of_one_unchanged_pipeline_name_nothing(self):
        """Counter-example (row 4): the one where the comparison is of a re-run.

        The empty string, which the caller records as a present and empty tag.
        An absent tag is indistinguishable from a comparison recorded before this
        rule existed, which is the argument R11.9 row 3 makes for `regressed`.
        """
        assert _line(("extract", StepStatus.CACHED), ("verify", StepStatus.CACHED)) == ""
