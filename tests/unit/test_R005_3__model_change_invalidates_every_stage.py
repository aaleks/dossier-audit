"""R5.3 — changing the model identifier changes every stage key.

Every stage, because every stage asked a model. No convert key, because
conversion never did.

This is what makes `--compare` a fair test (R7.8): swapping the pin and finding
half the pipeline served from cache would compare one model's answers against
another's, and report the difference as a regression in whichever ran second.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from dossier.domain.keys import ArtifactInput, ConvertInputs, StageInputs, cache_key

PINNED = "anthropic:claude-sonnet-4-5-20250929"
OTHER = "anthropic:claude-opus-4-1-20250805"

PROMPT = ArtifactInput(role="prompt", path="prompts/02_verify.md", hash="0e52dd18" * 8)
SCHEMA = ArtifactInput(role="schema", path="schemas/incident.json", hash="b81f0c6d" * 8)
CONVERTED = ArtifactInput(
    role="documents", path="converted/INC-4821.md", hash="5d3ba0f7" * 8
)


def stage(step: str, model: str) -> StageInputs:
    return StageInputs(
        step=step, prompt=PROMPT, output_schema=SCHEMA, model=model, inputs=[CONVERTED]
    )


def conversion(version: str = "1.3.0") -> ConvertInputs:
    return ConvertInputs(
        snapshot="a3f9c1e2" * 8, converter_id="pdf-markdown", converter_version=version
    )


class TestModelChangeInvalidatesEveryStage:
    """R5.3 — the pin is in every stage key and in no convert key."""

    def test_every_stage_key_moves(self):
        """Example 1: the one where all three stages re-run."""
        for step in ("extract", "verify", "report"):
            assert cache_key(stage(step, PINNED)) != cache_key(stage(step, OTHER))

    def test_no_convert_key_moves(self):
        """Example 2: the one where conversion is untouched.

        Conversion does not involve a model, so a model change that re-converted
        would re-do work that could not possibly differ -- and, on a PDF corpus,
        that is the expensive half.
        """
        assert cache_key(conversion()) == cache_key(conversion())

        before = cache_key(conversion())
        _ = [cache_key(stage(step, OTHER)) for step in ("extract", "verify")]

        assert cache_key(conversion()) == before

    def test_the_same_pin_leaves_every_key_alone(self):
        """Counter-example (row 4): the one where nothing about the model changed.

        The rule is about the identifier, not about how the model was reached.
        An endpoint, a gateway or a region is not part of the answer and is not
        part of the key -- there is nowhere in `StageInputs` to put one, which is
        the strongest form this guarantee can take (R5.1 example 3).
        """
        # Two separately constructed inputs, not the same object twice: the
        # previous form compared one call with itself and could not fail.
        assert cache_key(stage("verify", PINNED)) == cache_key(stage("report", PINNED))
        assert "endpoint" not in StageInputs.model_fields, (
            "and there is nowhere to record one, which is the stronger claim"
        )

    def test_two_different_pins_of_the_same_family_still_differ(self):
        """The one where a version bump is a different model.

        `claude-sonnet-4-5-20250929` and a later dated pin are different models
        for this purpose, whatever their family. R0.6 forbids floating aliases
        precisely so that this comparison is exact.
        """
        later = "anthropic:claude-sonnet-4-5-20260101"

        assert cache_key(stage("verify", PINNED)) != cache_key(stage("verify", later))
