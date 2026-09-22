"""R13.2 — a judged field publishes its rubric as one prompt named `<pipeline>.judge.<field>`.

A rubric is a prompt by every measure that matters: an author writes it, an edit
to it changes what a model is asked, and its hash gates a calibration (R7.14).
It is resolved against the pipeline's own directory like `prompts/` is, so its
name carries the pipeline too.

The name is the **field's**, not the step's, and that is what makes the dedup
fall out rather than needing a branch. `extract` and `verify` both declare
`schemas/incident.yaml`, so both see `root_cause`'s rubric -- and judging
`root_cause` is one job however many steps declare the field.

The declarations arrive per step, not pre-merged, precisely so this test can
prove the dedup happens here. A caller that flattened them first would be making
the decision R13.2 claims, and this file would be asserting the caller's work.
"""

from __future__ import annotations

from dossier.domain.hashing import content_hash
from dossier.domain.pipeline import PipelineConfig, StepConfig

MODEL = "anthropic:claude-sonnet-4-5-20250929"
RUBRIC = "Is the stated root cause supported by the named document?\n"


def _pipeline() -> PipelineConfig:
    """Two steps, both declaring the same field declaration -- as spec 003 writes them."""
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-jira"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract",
                prompt="prompts/01_extract.md",
                input="documents",
                mode="per_file",
                output="schemas/incident.yaml",
            ),
            StepConfig(
                id="verify",
                prompt="prompts/02_verify.md",
                input="documents",
                mode="per_file",
                output="schemas/incident.yaml",
            ),
        ],
    )


class TestAJudgedFieldPublishesItsRubric:
    """R13.2 — a judged field publishes its rubric as `<pipeline>.judge.<field>`."""

    def test_two_steps_declaring_one_field_declaration_publish_its_rubric_once(self):
        """Example 2: the one where judging `root_cause` is one job, not two.

        Three prompts, not four: the two steps' own prompts, and the rubric
        once. Tagged with the field rather than a step, because no step owns it
        -- naming it after either one would be a coin toss a reader could not
        reconstruct.
        """
        from dossier.domain.prompts import publish_set

        texts = {
            "prompts/01_extract.md": "Extract the fields.\n",
            "prompts/02_verify.md": "Verify the extraction.\n",
            "rubrics/root_cause.md": RUBRIC,
        }
        declared = {"root_cause": "rubrics/root_cause.md"}

        published = publish_set(
            _pipeline(), texts, rubrics={"extract": declared, "verify": declared}
        )

        assert [prompt.name for prompt in published] == [
            "incident-audit.extract",
            "incident-audit.verify",
            "incident-audit.judge.root_cause",
        ]
        rubric = published[-1]
        assert rubric.template == RUBRIC
        assert rubric.tags == {
            "dossier.prompt_hash": content_hash(RUBRIC.encode("utf-8")),
            "dossier.pipeline": "incident-audit",
            "dossier.field": "root_cause",
            "dossier.path": "rubrics/root_cause.md",
        }
        assert "dossier.step" not in rubric.tags, "no step owns a rubric"
