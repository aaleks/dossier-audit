"""R14.8 — a configured prefix goes in front of every prompt name; an unset one changes none.

The naming decision, in the layer that owns it. R14.1 and R14.2 compose a name
from the pipeline and the step or field; this puts it under a namespace. Pure,
so it is proved here in milliseconds rather than through a CLI, and the
acceptance test only has to show the namespace reaching a publish and a run.
"""

from __future__ import annotations

import pytest


class TestAPrefixGoesInFrontOfEveryPromptName:
    """R14.8 — a configured prefix goes in front of every prompt name."""

    def test_a_prefix_goes_in_front_of_a_step_s_name_and_a_rubric_s(self):
        """Row 1: the one where both kinds of prompt carry the namespace.

        A rubric has no less claim to a namespace than a step's prompt: two
        workspaces judging `root_cause` collide in exactly the same way.
        """
        from dossier.domain.prompts import judge_prompt_name, prompt_name

        assert prompt_name("incident-audit", "verify", prefix="sandbox") == (
            "sandbox.incident-audit.verify"
        )
        assert judge_prompt_name("incident-audit", "root_cause", prefix="sandbox") == (
            "sandbox.incident-audit.judge.root_cause"
        )

    def test_an_empty_prefix_leaves_the_name_exactly_as_composed(self):
        """Row 4: the one where a person who never sets the variable sees nothing change.

        Empty rather than merely absent, because `VAR=` in a `.env` file is how
        a person switches a setting off, and a namespace that appeared whenever
        the variable was present would split every existing history in two.
        """
        from dossier.domain.prompts import judge_prompt_name, prompt_name

        assert prompt_name("incident-audit", "verify", prefix="") == "incident-audit.verify"
        assert judge_prompt_name("incident-audit", "root_cause", prefix="") == (
            "incident-audit.judge.root_cause"
        )

    @pytest.mark.parametrize("prefix, character", [("team/a", "/"), ("team:a", ":")])
    def test_a_prefix_mlflow_cannot_hold_is_refused_naming_it(self, prefix, character):
        """Row 5: the one where the namespace is not a name MLflow takes.

        The variable is named as well as the character, because the person
        reading this did not type the prefix into the command -- it came from
        their environment or a `.env` file, and the message has to say which
        setting to go and change.
        """
        from dossier.domain.prompts import PROMPT_PREFIX, prompt_name

        with pytest.raises(ValueError) as refusal:
            prompt_name("incident-audit", "verify", prefix=prefix)

        assert character in str(refusal.value)
        assert PROMPT_PREFIX in str(refusal.value)
        assert PROMPT_PREFIX == "DOSSIER_MLFLOW_PROMPT_PREFIX"


class TestThePublishSetCarriesThePrefixToEveryName:
    """R14.8 — the projection names every prompt it produces under the prefix."""

    def test_every_prompt_the_projection_produces_is_namespaced(self):
        """Row 1, one layer down: the one where no name escapes the namespace.

        Steps and the rubric alike, and the rubric still once however many steps
        declare it (R14.2): the dedup compares names, so it has to compare the
        prefixed ones or two steps would publish `root_cause` twice.
        """
        from dossier.domain.pipeline import PipelineConfig, StepConfig
        from dossier.domain.prompts import publish_set

        config = PipelineConfig(
            name="incident-audit",
            sources=["incidents-jira"],
            model="anthropic:claude-sonnet-4-5-20250929",
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
        texts = {
            "prompts/01_extract.md": "Extract the fields.\n",
            "prompts/02_verify.md": "Verify the extraction.\n",
            "rubrics/root_cause.md": "Is the stated root cause supported?\n",
        }
        declared = {"root_cause": "rubrics/root_cause.md"}

        published = publish_set(
            config, texts, rubrics={"extract": declared, "verify": declared}, prefix="sandbox"
        )

        assert [prompt.name for prompt in published] == [
            "sandbox.incident-audit.extract",
            "sandbox.incident-audit.verify",
            "sandbox.incident-audit.judge.root_cause",
        ]
