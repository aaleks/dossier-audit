"""R11.11 — an eval records the version of everything it scored.

An eval recorded the model and the gold set and nothing else about what produced
the answers, so two evals five points apart in MLflow were two figures with no
stated cause. The manifest of the run being scored holds all of it, and an eval
already reads that manifest to reproduce the run.

Pure: a resolved plan in, params out. The values are `_fixtures.md`'s.
"""

from __future__ import annotations

from dossier.domain.resolution import (
    PinnedConverter,
    PinnedDocument,
    ResolvedPlan,
    ResolvedStep,
)
from dossier.domain.tracking import version_params

PIPELINE_HASH = "2f60a7d3"
SECOND_PIPELINE_HASH = "8ad3e115"


def _plan(*, pipeline_hash: str = PIPELINE_HASH) -> ResolvedPlan:
    """The `incident-audit` run of `_fixtures.md`, as its manifest pins it."""
    return ResolvedPlan(
        pipeline="incident-audit",
        pipeline_hash=pipeline_hash,
        model="anthropic:claude-sonnet-4-5-20250929",
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
            PinnedDocument(key="INC-4901", snapshot="0e52dd18"),
            PinnedDocument(key="INC-5455", snapshot="c4a70b93"),
        ],
        converters=[
            PinnedConverter(
                id="markdown-text",
                version="1.0.0",
                media_type="text/markdown",
                kind="markdown",
            ),
        ],
    )


class TestAnEvalRecordsTheVersionOfWhatItScored:
    """R11.11 — an eval records the version of everything it scored."""

    def test_the_params_name_the_pipeline_its_prompts_and_its_converters(self):
        """Example 1: the one where you ask which prompt produced what you scored."""
        recorded = version_params(_plan())

        assert recorded["pipeline_hash"] == PIPELINE_HASH
        assert recorded["prompt/extract"] == "77c1b40a"
        assert recorded["prompt/verify"] == "0e52dd18"
        assert recorded["schema/extract"] == "6e0d4b27"
        assert recorded["converters"] == "markdown-text 1.0.0"
        assert recorded["documents"] == "4"

    def test_a_generated_schema_is_recorded_too(self):
        """Example 4: the one where the declaration generates what the model saw.

        It is in the stage key (R6.12), so it is part of what produced the
        answer. A param for the declaration alone would name the file a person
        edits and not the thing the model was actually shown.
        """
        assert version_params(_plan())["generated_schema/extract"] == "d24c86e1"

    def test_a_step_that_generates_no_schema_records_none(self):
        """The boundary: `verify` declares no output, so it has no schema at all.

        Recorded as absent rather than as an empty string: a param reading
        `schema/verify=` says a schema was computed and came out empty, which is
        a different and alarming claim.
        """
        recorded = version_params(_plan())

        assert "schema/verify" not in recorded
        assert "generated_schema/verify" not in recorded

    def test_a_comparison_records_both_runs_under_their_own_prefixes(self):
        """Example 3: the one where the two runs are told apart.

        As `a/model` and `b/model` already are (R7.8). A single set of params
        would be a claim about both runs that is false in exactly the case the
        change gate exists for.
        """
        before = version_params(_plan(), prefix="a/")
        after = version_params(_plan(pipeline_hash=SECOND_PIPELINE_HASH), prefix="b/")

        assert before["a/pipeline_hash"] == PIPELINE_HASH
        assert after["b/pipeline_hash"] == SECOND_PIPELINE_HASH
        assert before.keys() != after.keys(), "two runs, two sets of names"

    def test_every_value_comes_from_the_plan_and_none_from_the_machine(self):
        """Counter-example (row 5): the one where the installed converter moved on.

        The plan pins `markdown-text 1.0.0`. Whatever is installed where the
        scoring happens, that is what is recorded -- otherwise two evals of one
        run on two laptops would disagree, and the record would describe the
        scoring machine rather than the run (R4.9).
        """
        moved = _plan().model_copy(
            update={
                "converters": [
                    PinnedConverter(
                        id="pdf-markdown",
                        version="1.3.0",
                        media_type="application/pdf",
                        kind="markdown",
                    )
                ]
            }
        )

        assert version_params(moved)["converters"] == "pdf-markdown 1.3.0"

    def test_converters_are_sorted_so_two_evals_of_one_run_read_alike(self):
        """The determinism boundary: a record is not an input, and is still stable.

        Nothing here enters a key (R10.4), so an unsorted list would break no
        rule -- and it would make two evals of one run differ in MLflow for no
        reason anybody could explain, which is its own kind of wrong (R0.4).
        """
        unsorted = _plan().model_copy(
            update={
                "converters": [
                    PinnedConverter(
                        id="pdf-markdown", version="1.3.0", media_type="a", kind="markdown"
                    ),
                    PinnedConverter(
                        id="markdown-text", version="1.0.0", media_type="b", kind="markdown"
                    ),
                ]
            }
        )

        assert (
            version_params(unsorted)["converters"] == "markdown-text 1.0.0, pdf-markdown 1.3.0"
        )
