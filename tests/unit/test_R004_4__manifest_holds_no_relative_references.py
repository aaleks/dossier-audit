"""R4.4 — the manifest contains only concrete ids.

No relative reference survives resolution. This is what makes a manifest
readable years later without the configuration that produced it: `previous` is
only meaningful beside the file it was written in, and that file is exactly what
a person reading an old run no longer has.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.resolution import resolve

PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8, "INC-4822": "77c1b40a" * 8}


def pipeline(**inputs: str | list[str]) -> PipelineConfig:
    """A pipeline whose steps read what the caller says, in declaration order."""
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(
                id=name, prompt="prompts/01_extract.md", input=value, mode="per_file"
            )
            for name, value in inputs.items()
        ],
    )


def resolved(config: PipelineConfig):
    return resolve(pipeline=config, pipeline_hash=PIPELINE_HASH, documents=DOCUMENTS)


class TestNoRelativeReferenceSurvives:
    """R4.4 — after resolution the word `previous` is gone."""

    def test_the_serialised_plan_never_says_previous(self):
        """Example 1: the one searched as text, not as structure.

        Asserted on the serialised bytes rather than on the input lists because
        that is the artifact a person actually reads. A field added later that
        happened to carry the raw reference would pass a structural check and
        fail this one.
        """
        plan = resolved(pipeline(extract="documents", verify="previous", report="previous(2)"))

        serialised = plan.model_dump_json()

        assert "previous" not in serialised
        assert "previous(" not in serialised

    def test_every_input_is_a_keyword_or_a_declared_step(self):
        """Example 2: the one where the ids are checked against what exists."""
        plan = resolved(pipeline(extract="documents", verify="previous", report="previous(2)"))

        legal = {"documents", "reference", *(step.id for step in plan.steps)}
        for step in plan.steps:
            assert set(step.inputs) <= legal, f"{step.id} reads something undeclared"

    def test_the_pipeline_hash_still_covers_the_file_as_written(self):
        """Counter-example (row 3): the one where `previous` is *supposed* to survive.

        The hash identifies the source; the inputs describe the run. A hash taken
        over the expanded form would stop matching the file on disk, and the
        manifest would name a `pipeline.yaml` that never existed.
        """
        plan = resolved(pipeline(extract="documents", verify="previous"))

        assert plan.pipeline_hash == PIPELINE_HASH

    def test_a_pipeline_without_sugar_resolves_to_itself(self):
        """The one where resolution is a no-op on an already-concrete pipeline."""
        plan = resolved(pipeline(extract="documents", verify="extract"))

        assert [step.inputs for step in plan.steps] == [["documents"], ["extract"]]

    def test_the_pinned_documents_travel_with_the_plan(self):
        """The one where a manifest says what it read, not just what it ran.

        Concrete ids alone would let two runs over different snapshots produce
        identical manifests, which is the opposite of what a manifest is for.
        """
        plan = resolved(pipeline(extract="documents"))

        assert {document.key: document.snapshot for document in plan.documents} == DOCUMENTS
