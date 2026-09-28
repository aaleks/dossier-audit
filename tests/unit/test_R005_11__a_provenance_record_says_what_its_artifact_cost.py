"""R5.11 — a provenance record says how many tokens its artifact cost, summed
over its attempts, and no key holds them.

Measured through a real run of `extract` over `INC-4821`, with a fake whose
replies say what they cost as a provider's would (R9.18). The record is read
where the cache writes it, beside the artifact under its key.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient, NoModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import RunInputs, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import Reply
from dossier.infrastructure.cache import ArtifactCache

RUN_ID = "20260806T142203Z-4f1a"
SECOND_RUN = "20260907T090000Z-bbbb"
STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8}
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
MODEL = "anthropic:claude-sonnet-4-5-20250929"
STAGE = Path(".dossier") / "cache" / "stage"

# Not JSON at all, so the attempt fails validation and is retried (R6.2).
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


def extract() -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract", prompt="prompts/01_extract.md", input="documents", mode="per_file"
            )
        ],
    )


def run(workspace: Path, model, *, run_id: str = RUN_ID):
    config = extract()
    return execute(
        RunInputs(
            pipeline=config,
            pipeline_hash=PIPELINE_HASH,
            schemas={"extract": SCHEMA},
            prompts={"extract": prompt_for(["documents"])},
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


def record_files(workspace: Path) -> list[Path]:
    root = workspace / STAGE
    return sorted(root.rglob("*.meta.json")) if root.is_dir() else []


def the_record(workspace: Path) -> dict:
    (only,) = record_files(workspace)
    return json.loads(only.read_text(encoding="utf-8"))


class TestAProvenanceRecordSaysWhatItsArtifactCost:
    """R5.11 — a provenance record says how many tokens its artifact cost, summed
    over its attempts, and no key holds them."""

    def test_an_answer_valid_first_time_records_what_it_cost(self, tmp_path: Path):
        """Row 1: the one where `INC-4821` is valid on its first attempt, at 1204/212."""
        run(
            tmp_path,
            FakeModelClient(responses=[Reply(answer(), input_tokens=1204, output_tokens=212)]),
        )

        record = the_record(tmp_path)
        assert record["tokens"] == {"input": 1204, "output": 212}
        assert record["attempts"] == 1

    def test_a_refused_attempt_is_in_the_sum(self, tmp_path: Path):
        """Row 2: the one valid on its second attempt, the two costing 1204/212 and 1391/230."""
        model = FakeModelClient(
            responses=[
                Reply(NONSENSE, input_tokens=1204, output_tokens=212),
                Reply(answer(), input_tokens=1391, output_tokens=230),
            ]
        )

        run(tmp_path, model)

        record = the_record(tmp_path)
        assert record["tokens"] == {"input": 2595, "output": 442}
        assert record["attempts"] == 2

    def test_a_cache_hit_keeps_the_cost_of_producing_it(self, tmp_path: Path):
        """Row 3: the one served from cache in `20260907T090000Z-bbbb`.

        The record says what producing the artifact cost, not what reading it
        did, so a hit leaves it byte for byte as it was written.
        """
        run(
            tmp_path,
            FakeModelClient(responses=[Reply(answer(), input_tokens=1204, output_tokens=212)]),
        )
        (path,) = record_files(tmp_path)
        written = path.read_bytes()

        run(tmp_path, NoModelClient(), run_id=SECOND_RUN)

        assert path.read_bytes() == written
        assert json.loads(written)["tokens"] == {"input": 1204, "output": 212}

    def test_a_provider_that_said_nothing_is_recorded_as_saying_nothing(self, tmp_path: Path):
        """Row 4: the one where the reply is plain text, with no counts on it."""
        run(tmp_path, FakeModelClient(responses=[answer()]))

        assert the_record(tmp_path)["tokens"] == {"input": None, "output": None}

    def test_a_partial_sum_is_not_the_sum(self, tmp_path: Path):
        """Row 5: the one where the first attempt reported and the second did not."""
        model = FakeModelClient(
            responses=[Reply(NONSENSE, input_tokens=1204, output_tokens=212), answer()]
        )

        run(tmp_path, model)

        assert the_record(tmp_path)["tokens"] == {"input": None, "output": None}

    def test_what_an_answer_cost_moves_no_key(self, tmp_path: Path):
        """Row 6, a counter-example: the same inputs answered at another token count."""
        cheap, dear = tmp_path / "cheap", tmp_path / "dear"
        run(
            cheap,
            FakeModelClient(responses=[Reply(answer(), input_tokens=1204, output_tokens=212)]),
        )
        run(
            dear,
            FakeModelClient(responses=[Reply(answer(), input_tokens=1391, output_tokens=230)]),
        )

        assert the_record(cheap)["cache_key"] == the_record(dear)["cache_key"]
        assert the_record(cheap)["tokens"] != the_record(dear)["tokens"]

    def test_a_document_that_failed_leaves_no_record_to_hold_its_cost(self, tmp_path: Path):
        """Row 7, a counter-example: the one that failed validation twice (R0.3 row 3)."""
        model = FakeModelClient(
            responses=[
                Reply(NONSENSE, input_tokens=1204, output_tokens=212),
                Reply(NONSENSE, input_tokens=1204, output_tokens=212),
            ]
        )

        report = run(tmp_path, model)

        assert report.failed == [("extract", "INC-4821")]
        assert record_files(tmp_path) == []
