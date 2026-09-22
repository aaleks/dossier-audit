"""R14.8 — a configured prefix goes in front of every prompt name, and an unset one changes none.

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
