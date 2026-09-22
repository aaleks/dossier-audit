"""R013.1 - what identifies and describes one pipeline version.

The acceptance test beside this one proves a run registers a version and that a
second run of the same pipeline finds it rather than making a second. This one
proves the projection: the name a version carries, the params that describe it,
and the pair that identifies it.

Pure, as the dataset projection is (spec 012). Nothing here reads a version
back; what comes off a server is a `PublishedVersion`, and R13.4 says where it
may go.
"""

from __future__ import annotations

import pytest

from dossier.domain.resolution import PinnedDocument, ResolvedPlan, ResolvedStep
from dossier.domain.versions import HASH_TAG, PIPELINE_TAG, version_record

PIPELINE = "incident-audit"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
HASH_A = "2f60a7d3"
HASH_B = "8ad3e115"


def _plan(*, pipeline: str = PIPELINE, pipeline_hash: str = HASH_A) -> ResolvedPlan:
    """The `incident-audit` run of `_fixtures.md`, as its manifest pins it."""
    return ResolvedPlan(
        pipeline=pipeline,
        pipeline_hash=pipeline_hash,
        model=MODEL,
        steps=[
            ResolvedStep(
                id="extract",
                inputs=["documents"],
                prompt_hash="77c1b40a",
                schema_hash="6e0d4b27",
                generated_schema_hash="d24c86e1",
            ),
            ResolvedStep(id="verify", inputs=["extract"], prompt_hash="0e52dd18"),
        ],
        documents=[
            PinnedDocument(key="INC-4821", snapshot="a3f9c1e2"),
            PinnedDocument(key="INC-4822", snapshot="77c1b40a"),
        ],
    )


class TestAVersionIsIdentifiedByItsPipelineAndHash:
    """R13.1 - the pair identifies; neither half does."""

    def test_a_version_is_named_after_its_pipeline(self):
        """The one where the row in the Models tab is readable.

        A person compares versions *of* a pipeline, so the pipeline's name is
        what the row is called. The hash tells them apart and is a param.
        """
        record = version_record(_plan())

        assert record.name == PIPELINE

    def test_the_identifying_pair_is_on_the_tags(self):
        """The one that makes a version findable again.

        MLflow creates a new logged model every time it is asked by name, so a
        version has to be *found* first -- and these two tags, together, are
        what finds it (R13.1 rows 4 and 5).
        """
        record = version_record(_plan())

        assert record.tags[PIPELINE_TAG] == PIPELINE
        assert record.tags[HASH_TAG] == record.params["version_hash"]
        assert record.params["pipeline_hash"] == HASH_A, (
            "the pipeline hash is recorded; it is just not the identity"
        )

    def test_a_version_carries_what_produced_it(self):
        """The one where the row says which prompts this version is.

        `version_params` (R11.18), so the run's record and the version's say the
        same thing about one plan because they are one function over one set of
        data.
        """
        record = version_record(_plan())

        assert record.params["pipeline_hash"] == HASH_A
        assert record.params["prompt/extract"] == "77c1b40a"
        assert record.params["schema/extract"] == "6e0d4b27"
        assert record.params["documents"] == "2"

    def test_the_llm_is_a_param_of_the_version_not_the_version_itself(self):
        """The one the spec's note about the word "model" is about.

        MLflow calls this object a logged model; dossier's *model* is the LLM.
        The pin is a param, so a version whose only change is the LLM is still a
        different row, and nobody reads the row as being the LLM.
        """
        record = version_record(_plan())

        assert record.params["model"] == MODEL
        assert record.name != MODEL

    @pytest.mark.parametrize(
        ("pipeline", "pipeline_hash", "why"),
        [
            (PIPELINE, HASH_B, "the same pipeline at another hash"),
            ("postmortem-review", HASH_A, "another pipeline at the same hash"),
        ],
    )
    def test_a_version_differing_in_either_half_is_another_version(
        self, pipeline: str, pipeline_hash: str, why: str
    ):
        """Counter-examples, rows 4 and 5: neither half identifies alone.

        The live spike settled this: filtering on the name alone returned two,
        and filtering on the hash alone returned two. Only the conjunction
        returned one, which is why both tags exist.
        """
        first = version_record(_plan())
        second = version_record(_plan(pipeline=pipeline, pipeline_hash=pipeline_hash))

        assert (first.tags[PIPELINE_TAG], first.tags[HASH_TAG]) != (
            second.tags[PIPELINE_TAG],
            second.tags[HASH_TAG],
        ), why

    def test_two_records_of_one_plan_are_equal(self):
        """The one that makes finding possible at all.

        A version projected twice from one plan is the same version, values and
        all. If it were not, a second run would register a second row and the
        comparison this spec exists for would compare a pipeline with itself
        (R0.4).
        """
        assert version_record(_plan()) == version_record(_plan())
