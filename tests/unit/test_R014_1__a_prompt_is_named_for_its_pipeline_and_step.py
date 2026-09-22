"""R14.1 — a step's prompt is named `<pipeline>.<step id>`.

The naming decision on its own, in the layer that owns it. It is pure: a
pipeline name and a step id go in, a string comes out, and nothing about it
needs a workspace, a server or a file on disk.

Two things it has to get right, and the second is the one that bites. The
separator is a dot because MLflow rejects `/` and `:` in a prompt name, so
`incident-audit/verify` was never available. And the name carries the pipeline
because a prompt name is global in MLflow while a prompt file is resolved
against the pipeline's own directory (spec 005) -- so `verify` alone would
interleave two pipelines' unrelated edits in one version history.
"""

from __future__ import annotations

import pytest


class TestAPromptIsNamedForItsPipelineAndStep:
    """R14.1 — every step of a pipeline publishes as one prompt named `<pipeline>.<step id>`."""

    def test_a_step_prompt_is_named_for_its_pipeline_and_its_step_id(self):
        """The one where the name carries the pipeline, so two pipelines are two prompts.

        `postmortem-review` is the second pipeline measured against the same gold
        set, and its `verify` step may hold a byte-identical prompt file. Two
        names, because one shared file must not become one shared history.
        """
        from dossier.domain.prompts import prompt_name

        assert prompt_name("incident-audit", "verify") == "incident-audit.verify"
        assert prompt_name("postmortem-review", "verify") == "postmortem-review.verify"

    def test_a_pipeline_name_mlflow_cannot_hold_is_refused_naming_the_character(self):
        """Row 5: the one where the name would be composed and then rejected by a server.

        A prompt name has two components and only one of them is constrained:
        R3.2 holds a step id to `[a-z][a-z0-9_]*`, while a pipeline's name is its
        directory under `pipelines/` and nothing checks it. Refused where the
        name is composed, so a person reads dossier's sentence rather than
        MLflow's traceback partway through a publish.

        Both characters, and each named in its own message -- a refusal that
        always said `/` would be a sentence that lies about half the cases.
        """
        from dossier.domain.prompts import prompt_name

        for pipeline, character in (("foo/bar", "/"), ("foo:bar", ":")):
            with pytest.raises(ValueError) as refusal:
                prompt_name(pipeline, "verify")
            assert character in str(refusal.value), f"the message must name {character!r}"
