"""R0.3 — every stage artifact has a sibling provenance record.

Each artifact is written with a `<name>.meta.json` naming its inputs by hash,
the prompt version, the schema version, the model identifier and the timestamp.

Measured through a real run of `extract` then `verify` over `INC-4821`. The
artifact is stored under its cache key, and its record beside it at
`<key>.meta.json`. The timestamp is the run id's: `20260806T142203Z-4f1a` is a
start time and a suffix (R0.7 row 4), recorded rather than keyed, so a record
says when its bytes were computed without moving the key that finds them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient, NoModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import RunInputs, _wrapped, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.hashing import content_hash
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

RUN_ID = "20260806T142203Z-4f1a"
STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8}
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
MODEL = "anthropic:claude-sonnet-4-5-20250929"
STAGE = Path(".dossier") / "cache" / "stage"

# Not JSON at all, so every attempt fails validation (R6.9).
NONSENSE = "no JSON here"


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


def pipeline() -> PipelineConfig:
    """`extract` over the documents, then `verify` over the documents and `extract`."""
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract", prompt="prompts/01_extract.md", input="documents", mode="per_file"
            ),
            StepConfig(
                id="verify",
                prompt="prompts/02_verify.md",
                input=["documents", "extract"],
                mode="per_file",
            ),
        ],
    )


def extract_only() -> PipelineConfig:
    """`extract` alone: the stage whose failure the counter-example is about."""
    config = pipeline()
    return config.model_copy(update={"steps": config.steps[:1]})


def run(workspace: Path, model, *, run_id: str = RUN_ID, config: PipelineConfig | None = None):
    config = config or pipeline()
    return execute(
        RunInputs(
            pipeline=config,
            pipeline_hash=PIPELINE_HASH,
            schemas=dict.fromkeys([step.id for step in config.steps], SCHEMA),
            prompts={step.id: prompt_for(step.inputs) for step in config.steps},
            documents=DOCUMENTS,
            document_text=STAGE_INPUTS,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


def records(workspace: Path) -> dict[str, tuple[Path, dict]]:
    """Each stage's record, by step, with the path it was found at."""
    found = {}
    for path in sorted((workspace / STAGE).rglob("*.meta.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        found[record["step"]] = (path, record)
    return found


def stage_files(workspace: Path) -> list[Path]:
    root = workspace / STAGE
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.is_dir() else []


class TestEveryArtifactHasAProvenanceRecord:
    """R0.3 — every stage artifact has a sibling provenance record."""

    def test_the_verify_artifact_has_its_record_beside_it(self, tmp_path: Path):
        """Example 1: the one where `verify` produces its artifact for `INC-4821`.

        The record sits beside the artifact and names what it was computed from:
        the document and the `extract` artifact by hash, the prompt, the schema,
        the model, and the run that computed it.
        """
        run(tmp_path, FakeModelClient(responses=[answer(), answer()]))

        found = records(tmp_path)
        extract_path, _ = found["extract"]
        verify_path, record = found["verify"]
        artifact = verify_path.with_name(verify_path.name.removesuffix(".meta.json"))
        extracted = extract_path.with_name(extract_path.name.removesuffix(".meta.json"))

        assert artifact.is_file()
        assert artifact.name == record["cache_key"]
        # The hash of the value the stage was *given*, which since R3.13 names
        # the document it came from. Built with `_wrapped` rather than with a
        # second copy of the format string, so this states the claim -- the
        # record holds the hashes of the inputs -- instead of restating the
        # wrapper.
        assert {entry["role"]: entry["hash"] for entry in record["inputs"]} == {
            "documents": content_hash(_wrapped("INC-4821", STAGE_INPUTS["INC-4821"]).encode()),
            "extract": content_hash(
                _wrapped("INC-4821", extracted.read_text(encoding="utf-8")).encode()
            ),
        }
        assert record["prompt"]["hash"] == content_hash(
            prompt_for(["documents", "extract"]).encode()
        )
        assert record["schema"]["hash"] == SCHEMA.declaration_hash
        assert record["model"] == MODEL
        assert record["run_id"] == RUN_ID

    def test_a_cache_hit_keeps_the_record_it_was_computed_with(self, tmp_path: Path):
        """Example 2: the one served from cache rather than recomputed.

        Present and identical (R5.5): the record describes the run that computed
        the bytes, and a later run that only read them does not rewrite it.
        """
        run(tmp_path, FakeModelClient(responses=[answer(), answer()]))
        before = {step: record for step, (_, record) in records(tmp_path).items()}

        report = run(tmp_path, NoModelClient(), run_id="20260907T090000Z-bbbb")

        assert report.cache_hits == 2
        assert {step: record for step, (_, record) in records(tmp_path).items()} == before

    def test_a_document_that_fails_validation_leaves_neither(self, tmp_path: Path):
        """Counter-example (row 3): the one where `INC-4821` fails validation twice.

        No artifact and no provenance record: the failure is reported, not
        recorded as an output (R6.9). A record with no artifact would describe
        bytes that do not exist.
        """
        report = run(
            tmp_path, FakeModelClient(responses=[NONSENSE, NONSENSE]), config=extract_only()
        )

        (failed,) = report.steps[0].results
        assert failed.failed
        assert "INC-4821" in failed.error
        assert stage_files(tmp_path) == []
