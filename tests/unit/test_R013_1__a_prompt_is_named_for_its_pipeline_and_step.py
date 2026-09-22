"""R13.1 — a step's prompt is named `<pipeline>.<step id>`.

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


class TestAPromptIsNamedForItsPipelineAndStep:
    """R13.1 — every step of a pipeline publishes as one prompt named `<pipeline>.<step id>`."""

    def test_a_step_prompt_is_named_for_its_pipeline_and_its_step_id(self):
        """The one where the name carries the pipeline, so two pipelines are two prompts.

        `postmortem-review` is the second pipeline measured against the same gold
        set, and its `verify` step may hold a byte-identical prompt file. Two
        names, because one shared file must not become one shared history.
        """
        from dossier.domain.prompts import prompt_name

        assert prompt_name("incident-audit", "verify") == "incident-audit.verify"
        assert prompt_name("postmortem-review", "verify") == "postmortem-review.verify"
