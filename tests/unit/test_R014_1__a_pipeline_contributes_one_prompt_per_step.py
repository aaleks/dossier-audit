"""R14.1 — a pipeline contributes one prompt per step, named and holding its own text.

The projection itself: a loaded pipeline goes in, the set of prompts to publish
comes out. Pure, because `publish_set` is handed the text of each prompt rather
than reading it -- the caller does the IO, and the decision about what is
published under which name stays testable in milliseconds.

Keyed by the path each step writes, so two steps naming one file resolve to the
same text and still publish as two prompts (R14.1 row 3): a prompt is named for
the job it does, not the file it sits in.
"""

from __future__ import annotations

from dossier.domain.pipeline import PipelineConfig, StepConfig

MODEL = "anthropic:claude-sonnet-4-5-20250929"


def _pipeline() -> PipelineConfig:
    """The three steps of `incident-audit`, as spec 003 writes them."""
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-jira"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract", prompt="prompts/01_extract.md", input="documents", mode="per_file"
            ),
            StepConfig(
                id="verify", prompt="prompts/02_verify.md", input="documents", mode="per_file"
            ),
            StepConfig(
                id="report", prompt="prompts/03_report.md", input="verify", mode="aggregate"
            ),
        ],
    )


class TestAPipelineContributesOnePromptPerStep:
    """R14.1 — every step of a pipeline publishes as one prompt named `<pipeline>.<step id>`."""

    def test_each_step_contributes_one_named_prompt_holding_its_own_text(self):
        """The one where three steps become three prompts, in the order they are declared.

        Declaration order rather than sorted, because that is the order a person
        reads the pipeline in and the order the terminal line will print. Each
        prompt holds the text of the file its own step names -- the projection
        does not read, so a step whose text is missing is the caller's problem.
        """
        from dossier.domain.prompts import publish_set

        texts = {
            "prompts/01_extract.md": "Extract the fields.\n",
            "prompts/02_verify.md": "Verify the extraction.\n",
            "prompts/03_report.md": "Report on every document.\n",
        }

        published = publish_set(_pipeline(), texts)

        assert [prompt.name for prompt in published] == [
            "incident-audit.extract",
            "incident-audit.verify",
            "incident-audit.report",
        ]
        assert [prompt.template for prompt in published] == [
            "Extract the fields.\n",
            "Verify the extraction.\n",
            "Report on every document.\n",
        ]
