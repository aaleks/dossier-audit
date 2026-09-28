"""R5.2 — changing a prompt changes that stage's key and every downstream key, and
no upstream key.

The cascade in one sentence.

Both halves of it are load-bearing and they fail in opposite directions. A change
that did not propagate downstream would serve a `report` written against an
answer `verify` no longer gives — stale, and invisible, because the report reads
perfectly well. A change that propagated *upstream* would re-extract the whole
corpus because somebody fixed a typo three stages later, which is the cost the
cache exists to avoid.

The key-level claims are asserted directly; the cache ones are measured through a
real run, because "the key is different" and "the model was actually asked again"
are different statements and the rule needs the second.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import RunInputs, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.keys import ArtifactInput, ConvertInputs, StageInputs, cache_key
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8, "INC-4822": "77c1b40a" * 8}

TEXT = {
    key: STAGE_INPUTS["INC-4821"].replace("INC-4821", key) + f"\n\nFiled as {key}.\n"
    for key in DOCUMENTS
}

STEPS = ("extract", "verify", "report")


def answer(document: str, value: float = 48200.00) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "loss_amount",
                    "value": value,
                    "currency": "CHF",
                    "source": {"document": document, "span": LOSS_SPAN},
                }
            ],
        }
    )


def pipeline() -> PipelineConfig:
    """`extract` -> `verify` -> `report`, each reading the one before it."""
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(
                id="extract",
                prompt="prompts/01_extract.md",
                input="documents",
                mode="per_file",
            ),
            StepConfig(
                id="verify",
                prompt="prompts/02_verify.md",
                input="extract",
                mode="per_file",
            ),
            StepConfig(
                id="report",
                prompt="prompts/03_report.md",
                input="verify",
                mode="per_file",
            ),
        ],
    )


def run(workspace: Path, model, *, prompts: dict[str, str], run_id: str):
    config = pipeline()
    return execute(
        RunInputs(
            pipeline=config,
            pipeline_hash=PIPELINE_HASH,
            schemas=dict.fromkeys(STEPS, SCHEMA),
            prompts=prompts,
            documents=DOCUMENTS,
            document_text=TEXT,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


def default_prompts() -> dict[str, str]:
    config = pipeline()
    return {step.id: prompt_for(step.inputs) for step in config.steps}


def responses(count: int, value: float = 48200.00) -> list[str]:
    keys = list(DOCUMENTS)
    return [answer(key, value) for _ in range(count) for key in keys]


def stage_key(prompt: str, *, input_hash: str = "77c1b40a" * 8) -> str:
    """A stage key over one prompt and one input, with everything else fixed."""
    return cache_key(
        StageInputs(
            step="verify",
            prompt=ArtifactInput(
                role="prompt", path="prompts/02_verify.md", hash=_hash(prompt)
            ),
            output_schema=ArtifactInput(
                role="schema", path="schemas/incident.json", hash="b81f0c6d" * 8
            ),
            model="anthropic:claude-sonnet-4-5-20250929",
            inputs=[
                ArtifactInput(role="extract", path="extract/INC-4821.json", hash=input_hash)
            ],
        )
    )


def _hash(text: str) -> str:
    from dossier.domain.hashing import content_hash

    return content_hash(text.encode())


class TestThePromptCascade:
    """R5.2 — down the chain, never up it."""

    def test_editing_a_prompt_reruns_that_stage_and_the_one_below(self, tmp_path: Path):
        """Example 1: the one where `verify` and `report` both move."""
        prompts = default_prompts()
        run(
            tmp_path,
            FakeModelClient(responses=responses(3)),
            prompts=prompts,
            run_id="20260806T142203Z-4f1a",
        )

        edited = {**prompts, "verify": prompts["verify"] + "\nBe strict about currency.\n"}
        # The stricter prompt gets a different answer, which is what a real model
        # does and what carries the change past `verify`. The cascade is over
        # content: `report` re-runs because its input moved, not because the step
        # above it happened to run. That is `K_stage` as spec 005 composes it.
        model = FakeModelClient(responses=responses(1, value=48250.00) + responses(1))
        report = run(tmp_path, model, prompts=edited, run_id="20260907T090000Z-bbbb")

        assert model.call_count == 4, "two documents through `verify` and through `report`"
        assert report.steps[1].served_from_cache == ()
        assert report.steps[2].served_from_cache == ()

    def test_the_stage_above_is_untouched(self, tmp_path: Path):
        """Example 2: the one where `extract` is still served from cache.

        This is the half that pays for the cache. Editing a prompt three stages
        down must not re-extract a corpus, and a cascade written to propagate in
        both directions would look correct on every other row in this file.
        """
        prompts = default_prompts()
        run(
            tmp_path,
            FakeModelClient(responses=responses(3)),
            prompts=prompts,
            run_id="20260806T142203Z-4f1a",
        )

        edited = {**prompts, "verify": prompts["verify"] + "\nBe strict about currency.\n"}
        report = run(
            tmp_path,
            FakeModelClient(responses=responses(1, value=48250.00) + responses(1)),
            prompts=edited,
            run_id="20260907T090000Z-bbbb",
        )

        assert len(report.steps[0].served_from_cache) == len(DOCUMENTS)
        assert report.steps[0].step == "extract"

    def test_no_convert_key_moves(self):
        """Example 3: the one where nothing is re-converted and nothing re-fetched.

        A convert key is composed of the snapshot hash and the converter's
        identity and options -- a prompt is not among them, and there is nowhere
        in `ConvertInputs` to put one. That is the strongest form this guarantee
        takes: not that the prompt is excluded, but that it cannot be included.
        """
        conversion = ConvertInputs(
            snapshot="a3f9c1e2" * 8, converter_id="pdf-markdown", converter_version="1.3.0"
        )

        # `cache_key(x) == cache_key(x)` used to stand here and could not fail.
        # The claim is that a prompt has nowhere to go in a convert key, which is
        # a statement about the structure rather than about two equal calls.
        assert "prompt" not in conversion.keyed()
        assert set(conversion.keyed()) == {
            "snapshot",
            "converter_id",
            "converter_version",
            "options",
        }

    def test_trailing_whitespace_changes_the_key(self):
        """Counter-example (row 4): the one where a "harmless" edit is not harmless.

        The prompt is hashed as bytes. A trailing newline is indistinguishable
        from a real edit, and a cache that tried to tell them apart would be
        deciding which edits matter -- which is the model's job, not the cache's.
        """
        prompt = "<extraction>{{extract}}</extraction>"

        assert stage_key(prompt) != stage_key(prompt + "\n")
        assert stage_key(prompt) != stage_key(prompt + " ")

    def test_an_unedited_prompt_changes_nothing(self, tmp_path: Path):
        """The one where the cascade is not simply "always re-run".

        A second run with the same prompts must cost nothing. Without this, every
        assertion above is satisfied by a cache that never hits.
        """
        prompts = default_prompts()
        run(
            tmp_path,
            FakeModelClient(responses=responses(3)),
            prompts=prompts,
            run_id="20260806T142203Z-4f1a",
        )

        model = FakeModelClient(responses=[])
        report = run(tmp_path, model, prompts=prompts, run_id="20260907T090000Z-bbbb")

        assert model.call_count == 0
        assert report.cache_hits == len(DOCUMENTS) * len(STEPS)

    def test_editing_the_last_prompt_moves_only_its_own_key(self, tmp_path: Path):
        """The one where there is nothing downstream to cascade to.

        `report` is last. Editing it re-runs it and nothing else, which is the
        same rule seen from the bottom of the chain.
        """
        prompts = default_prompts()
        run(
            tmp_path,
            FakeModelClient(responses=responses(3)),
            prompts=prompts,
            run_id="20260806T142203Z-4f1a",
        )

        edited = {**prompts, "report": prompts["report"] + "\nOne page maximum.\n"}
        model = FakeModelClient(responses=responses(1))
        report = run(tmp_path, model, prompts=edited, run_id="20260907T090000Z-bbbb")

        assert model.call_count == len(DOCUMENTS)
        assert len(report.steps[0].served_from_cache) == len(DOCUMENTS)
        assert len(report.steps[1].served_from_cache) == len(DOCUMENTS)
        assert report.steps[2].served_from_cache == ()
