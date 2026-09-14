"""R5.7 — adding a document re-runs stages for that document only.

This is the rule that makes an audit affordable to keep current. A corpus grows
by one document a week; a pipeline that re-ran everything each time would cost
its whole corpus per addition, and the cost of adding the 421st document would be
421 documents' worth of calls.

The `aggregate` step is the deliberate exception, and it is the interesting half.
A step that reads *every* input has a key over every input, so one new document
moves it — correctly. That is not a failure of incrementality; it is what
"aggregate" means, and a run that served a cached report over 420 documents when
421 exist would be reporting on a corpus that no longer exists.

The rows below are the rule's example table, transcribed. 420 documents are
represented by six: the claim is about which documents are re-run, and six is
enough to distinguish "the new one" from "all of them" while keeping the test
readable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import AGGREGATE_KEY, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)

HELD = ["INC-4821", "INC-4822", "INC-4901", "INC-5044", "INC-5102", "INC-5230"]
ADDED = "INC-5310"


def answer(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "loss_amount",
                    "value": 48200.00,
                    "currency": "CHF",
                    "source": {"document": document, "span": LOSS_SPAN},
                }
            ],
        }
    )


def text_for(keys: list[str]) -> dict[str, str]:
    """Distinct text per document, so each is its own computation."""
    return {
        key: STAGE_INPUTS["INC-4821"].replace("INC-4821", key) + f"\n\nFiled as {key}.\n"
        for key in keys
    }


def pipeline(*, with_report: bool) -> PipelineConfig:
    steps = [
        StepConfig(
            id="extract", prompt="prompts/extract.md", input="documents", mode="per_file"
        ),
        StepConfig(
            id="verify",
            prompt="prompts/verify.md",
            input=["documents", "extract"],
            mode="per_file",
        ),
    ]
    if with_report:
        steps.append(
            StepConfig(
                id="report", prompt="prompts/report.md", input="verify", mode="aggregate"
            )
        )
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=steps,
    )


def run(workspace: Path, model, *, keys: list[str], with_report: bool, run_id: str):
    config = pipeline(with_report=with_report)
    return execute(
        workspace=workspace,
        pipeline=config,
        pipeline_hash=PIPELINE_HASH,
        documents={key: f"{index:064d}" for index, key in enumerate(keys)},
        document_text=text_for(keys),
        schemas={step.id: SCHEMA for step in config.steps if step.mode == "per_file"},
        prompts={step.id: prompt_for(step.inputs) for step in config.steps},
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


def scripted(keys: list[str], *, aggregate: bool = False) -> list[str]:
    """Enough answers for `extract` and `verify` over `keys`, plus a report."""
    responses = [answer(key) for key in keys] * 2
    return [*responses, "The corpus was audited."] if aggregate else responses


class TestOnlyTheNewDocumentReruns:
    """R5.7 — the 421st document costs one document, not 421."""

    def test_the_per_file_stages_run_once_each_for_the_new_document(self, tmp_path: Path):
        """Example 1: the one where six documents are already paid for."""
        run(
            tmp_path,
            FakeModelClient(responses=scripted(HELD)),
            keys=HELD,
            with_report=False,
            run_id="20260806T142203Z-4f1a",
        )

        grown = [*HELD, ADDED]
        model = FakeModelClient(responses=scripted([ADDED]))
        report = run(
            tmp_path, model, keys=grown, with_report=False, run_id="20260907T090000Z-bbbb"
        )

        assert model.call_count == 2, "one `extract` and one `verify`, for the new document"
        assert report.cache_hits == len(HELD) * 2

    def test_the_aggregate_step_reruns_because_it_reads_everything(self, tmp_path: Path):
        """Example 2: the one where `report` correctly does not get a cache hit.

        Its key is over every input artifact, so one new document moves it. A run
        that served the old report here would be describing a corpus of six when
        seven exist -- which is the failure this row exists to name.
        """
        run(
            tmp_path,
            FakeModelClient(responses=scripted(HELD, aggregate=True)),
            keys=HELD,
            with_report=True,
            run_id="20260806T142203Z-4f1a",
        )

        grown = [*HELD, ADDED]
        model = FakeModelClient(responses=scripted([ADDED], aggregate=True))
        report = run(
            tmp_path, model, keys=grown, with_report=True, run_id="20260907T090000Z-bbbb"
        )

        assert [step.step for step in report.steps] == ["extract", "verify", "report"]
        assert report.steps[2].served_from_cache == ()

    def test_the_calls_are_exactly_two_per_file_plus_one_aggregate(self, tmp_path: Path):
        """Example 3: the one counted at the model client.

        The count is the whole claim. Three calls for a seventh document, not
        fifteen, and one of the three is the aggregate step doing the thing that
        makes it an aggregate step.
        """
        run(
            tmp_path,
            FakeModelClient(responses=scripted(HELD, aggregate=True)),
            keys=HELD,
            with_report=True,
            run_id="20260806T142203Z-4f1a",
        )

        grown = [*HELD, ADDED]
        model = FakeModelClient(responses=scripted([ADDED], aggregate=True))
        run(tmp_path, model, keys=grown, with_report=True, run_id="20260907T090000Z-bbbb")

        assert model.call_count == 3

    def test_a_duplicate_document_is_served_from_cache(self, tmp_path: Path):
        """Counter-example (row 4): the one where the new document is not new.

        Added under a different key with identical text. The stage key is over
        input *hashes*, not over document names, so it is the same computation
        and the model is never asked. Keying on the name would re-run it and
        charge for an answer already held.
        """
        run(
            tmp_path,
            FakeModelClient(responses=scripted(HELD)),
            keys=HELD,
            with_report=False,
            run_id="20260806T142203Z-4f1a",
        )

        config = pipeline(with_report=False)
        duplicate = "INC-9999"
        keys = [*HELD, duplicate]
        text = text_for(HELD)
        text[duplicate] = text["INC-4821"]

        model = FakeModelClient(responses=[])
        report = execute(
            workspace=tmp_path,
            pipeline=config,
            pipeline_hash=PIPELINE_HASH,
            documents={key: f"{index:064d}" for index, key in enumerate(keys)},
            document_text=text,
            schemas={"extract": SCHEMA, "verify": SCHEMA},
            prompts={step.id: prompt_for(step.inputs) for step in config.steps},
            model=model,
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260907T090000Z-cccc",
            started_at=STARTED_AT,
            dossier_version="0.1.0",
        )

        assert model.call_count == 0
        assert report.cache_hits == len(keys) * 2


class TestWhatAnAggregateStepIs:
    """The mode itself, which R5.7 examples 2 and 3 depend on."""

    def test_it_asks_the_model_once_however_many_documents_there_are(self, tmp_path: Path):
        """The one that distinguishes `aggregate` from `per_file`.

        Six documents, one call. A step that quietly ran per-file would produce
        six answers to a question asked about the corpus, at six times the price.
        """
        model = FakeModelClient(responses=scripted(HELD, aggregate=True))

        report = run(
            tmp_path, model, keys=HELD, with_report=True, run_id="20260806T142203Z-4f1a"
        )

        assert len(report.steps[2].results) == 1
        assert model.call_count == len(HELD) * 2 + 1

    def test_every_document_appears_in_the_prompt_under_its_own_key(self, tmp_path: Path):
        """The one where the join convention is visible to the model.

        Spec 003: each document wrapped in a tag naming its key, in key order, so
        a finding can be attributed and the prompt is the same on every machine.
        """
        model = FakeModelClient(responses=scripted(HELD, aggregate=True))

        run(tmp_path, model, keys=HELD, with_report=True, run_id="20260806T142203Z-4f1a")

        aggregate_prompt = model.calls[-1]["prompt"]
        for key in HELD:
            assert f'<document key="{key}">' in aggregate_prompt
        positions = [aggregate_prompt.index(f'key="{key}"') for key in sorted(HELD)]
        assert positions == sorted(positions), "documents appear in key order"

    def test_a_step_without_a_schema_may_answer_in_prose(self, tmp_path: Path):
        """The one R3.5's counter-example allows.

        `report` declares no `output`, so there is no schema and nothing to
        validate against. The prose is kept as the step's result rather than
        parsed into fields it was never asked for.
        """
        model = FakeModelClient(responses=scripted(HELD, aggregate=True))

        report = run(
            tmp_path, model, keys=HELD, with_report=True, run_id="20260806T142203Z-4f1a"
        )

        result = report.steps[2].results[0]
        assert result.document == AGGREGATE_KEY
        assert result.text == "The corpus was audited."
        assert result.records == ()

    def test_an_unchanged_corpus_serves_the_aggregate_step_from_cache(self, tmp_path: Path):
        """The one where an aggregate step is still cached when nothing moved.

        It re-runs when the corpus changes, not on principle. Two identical runs
        must cost nothing the second time, or the expensive step would be the one
        that never benefits from the cache at all.
        """
        run(
            tmp_path,
            FakeModelClient(responses=scripted(HELD, aggregate=True)),
            keys=HELD,
            with_report=True,
            run_id="20260806T142203Z-4f1a",
        )

        model = FakeModelClient(responses=[])
        report = run(
            tmp_path, model, keys=HELD, with_report=True, run_id="20260907T090000Z-bbbb"
        )

        assert model.call_count == 0
        assert len(report.steps[2].served_from_cache) == 1
