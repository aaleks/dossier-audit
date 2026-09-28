"""R0.5 — anything that can change an output is part of that output's cache key.

If changing something changes the result, changing it invalidates the cache. The
contrapositive is the useful half: a cache hit is a promise that nothing relevant
changed.

Rows 1 to 3 are claims about keys, asserted on the keys themselves, built as
spec 005's `verify` example builds them. Row 4 is a claim that something does
*not* move a key, and is measured through two real runs with the cache deleted
between them -- a key that read anything from the cache would show it there.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import RunInputs, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.keys import ArtifactInput, StageInputs, cache_key
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

CONVERTED = ArtifactInput(role="documents", path="converted/INC-4821.md", hash="5d3ba0f7" * 8)
EXTRACTED = ArtifactInput(role="extract", path="extract/INC-4821.json", hash="77c1b40a" * 8)
PROMPT = ArtifactInput(role="prompt", path="prompts/02_verify.md", hash="0e52dd18" * 8)
SCHEMA = ArtifactInput(role="schema", path="schemas/incident.json", hash="b81f0c6d" * 8)

PINNED = "anthropic:claude-sonnet-4-5-20250929"
ANOTHER_PIN = "anthropic:claude-opus-4-1-20250805"
EDITED = "a3f9c1e2" * 8


def verify_stage(**overrides) -> StageInputs:
    """The `verify` artifact for `INC-4821`, as spec 005's provenance example."""
    fields = {
        "step": "verify",
        "prompt": PROMPT,
        "output_schema": SCHEMA,
        "model": PINNED,
        "inputs": [CONVERTED, EXTRACTED],
    }
    return StageInputs(**{**fields, **overrides})


def extract_stage(**overrides) -> StageInputs:
    """The `extract` artifact for `INC-4821`, reading the converted document."""
    fields = {
        "step": "extract",
        "prompt": ArtifactInput(
            role="prompt", path="prompts/01_extract.md", hash="6e0d4b27" * 8
        ),
        "output_schema": SCHEMA,
        "model": PINNED,
        "inputs": [CONVERTED],
    }
    return StageInputs(**{**fields, **overrides})


def answer() -> str:
    return json.dumps(
        {
            "document": "INC-4821",
            "fields": [
                {
                    "field": "loss_amount",
                    "value": 48200.00,
                    "currency": "CHF",
                    "source": {"document": "INC-4821", "span": LOSS_SPAN},
                }
            ],
        }
    )


def run(workspace: Path, run_id: str) -> list[str]:
    """One real run of `extract` then `verify`; the keys its records name, sorted."""
    config = PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model=PINNED,
        steps=[
            StepConfig(
                id="extract", prompt="prompts/01_extract.md", input="documents", mode="per_file"
            ),
            StepConfig(
                id="verify", prompt="prompts/02_verify.md", input="extract", mode="per_file"
            ),
        ],
    )
    execute(
        RunInputs(
            pipeline=config,
            pipeline_hash="0e52dd18" * 8,
            schemas=dict.fromkeys(
                ["extract", "verify"],
                OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8),
            ),
            prompts={step.id: prompt_for(step.inputs) for step in config.steps},
            documents={"INC-4821": "a3f9c1e2" * 8},
            document_text=STAGE_INPUTS,
        ),
        workspace=workspace,
        model=FakeModelClient(responses=[answer(), answer()]),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
    )
    return sorted(
        json.loads(path.read_text(encoding="utf-8"))["cache_key"]
        for path in (workspace / ".dossier" / "cache").rglob("*.meta.json")
    )


class TestKeyCoversEveryOutputDeterminingInput:
    """R0.5 — anything that can change an output is part of that output's cache key."""

    def test_editing_the_verify_prompt_moves_the_verify_key(self):
        """Example 1: the one where `prompts/02_verify.md` is edited."""
        edited = verify_stage(prompt=PROMPT.model_copy(update={"hash": EDITED}))

        assert cache_key(edited) != cache_key(verify_stage())

    def test_editing_the_schema_moves_the_verify_key(self):
        """Example 2: the one where `schemas/incident.json` is edited."""
        edited = verify_stage(output_schema=SCHEMA.model_copy(update={"hash": EDITED}))

        assert cache_key(edited) != cache_key(verify_stage())

    def test_changing_the_pinned_model_moves_every_stage_key(self):
        """Example 3: the one where the pin changes to `claude-sonnet-4-5-20250929`.

        From another pin, to it. Every stage asks the model, so every stage key
        moves -- `extract` as well as `verify` (R5.3).
        """
        for stage in (extract_stage, verify_stage):
            assert cache_key(stage(model=PINNED)) != cache_key(stage(model=ANOTHER_PIN))

    def test_deleting_the_cache_moves_no_key(self, tmp_path: Path):
        """Counter-example (row 4): the one where the cache directory is deleted.

        No key changes; only the time taken (R5.9). A key is computed from the
        inputs, never from what happens to be stored, so the second run asks for
        exactly the entries the first one wrote.
        """
        before = run(tmp_path, "20260806T142203Z-4f1a")
        shutil.rmtree(tmp_path / ".dossier" / "cache")

        after = run(tmp_path, "20260907T090000Z-bbbb")

        assert len(before) == 2
        assert after == before

    def test_text_dossier_itself_authors_is_in_no_key_and_in_every_record(self, tmp_path: Path):
        """Counter-example (row 5): the one where dossier, not the pipeline, changed.

        A stage key is composed of exactly six things, none of them the retry
        wrapper or a client's request ceiling; what version of dossier said
        them is in the record beside the artifact, where a person can read it
        and no output depends on it (R5.1 row 4).
        """
        from dossier.application.extract import CORRECTION_TEMPLATE
        from dossier.domain.keys import canonical

        stage = verify_stage()

        assert set(stage.keyed()) == {
            "prompt",
            "schema",
            "generated_schema",
            "model",
            "options",
            "inputs",
        }
        assert CORRECTION_TEMPLATE.encode("utf-8")[:24] not in canonical(stage)
        run(tmp_path, "20260806T142203Z-4f1a")
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (tmp_path / ".dossier" / "cache").rglob("*.meta.json")
        ]
        assert records and all(record["dossier_version"] == "0.1.0" for record in records)
