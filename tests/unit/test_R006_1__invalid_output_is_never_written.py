"""R6.1 — output that does not validate against its schema is never written and
never cached.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json

import pytest
from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS

from dossier.application.extract import run_stage
from dossier.domain.fields import OutputSchema

PROMPT = "<source_document>{{documents}}</source_document>"
SCHEMA = {"type": "object"}
# The same schema as a declaration hands it to `execute`: `run_stage` takes the
# schema alone, a run takes it with the declaration's hash for the key (R6.11).
OUTPUT = OutputSchema(schema=SCHEMA, declaration_hash="6e0d4b27" * 8)


def valid(**overrides) -> str:
    field = {
        "field": "loss_amount",
        "value": 48200.00,
        "currency": "CHF",
        "source": {"document": "INC-4821", "span": LOSS_SPAN, "page": 3},
    } | overrides
    return json.dumps({"document": "INC-4821", "fields": [field]})


def run(responses: list[str]):
    return run_stage(
        document="INC-4821",
        prompt=PROMPT,
        schema=SCHEMA,
        model=FakeModelClient(responses=list(responses)),
        input_documents=STAGE_INPUTS,
    )


class TestInvalidOutputIsNeverWritten:
    """R6.1 — nothing malformed reaches disk or the cache."""

    def test_a_wrongly_typed_value_fails_the_document(self):
        """Example 1: the one where the model answered in prose.

        `"quite a lot"` against a numeric field, twice. Nothing to write, nothing
        to cache, and the document reported as failed.
        """
        wrong_type = json.dumps(
            {"document": "INC-4821", "fields": [{"field": "loss_amount", "value": []}]}
        )

        result = run([wrong_type, wrong_type])

        assert result.failed
        assert result.records == ()

    def test_an_unknown_extra_field_is_rejected(self):
        """Example 2: the one where the schema is closed.

        A field nobody declared is a silent contract change. Accepting it means
        the next reader of this artifact sees data that no schema describes and
        no scorer will ever look at.
        """
        extra = json.dumps({"document": "INC-4821", "fields": [], "confidence_overall": "high"})

        assert run([extra, extra]).failed

    def test_prose_instead_of_json_is_rejected(self):
        """Example 3: the one where the answer is not JSON at all.

        Counted as a validation failure for retry purposes, so the model gets one
        chance to be told it must return JSON (R6.2).
        """
        result = run(["I could not find the loss amount.", valid()])

        assert result.failed is False
        assert result.attempts == 2

    def test_a_failed_document_produces_no_records_to_write(self):
        """The one that makes "never written" checkable here.

        This layer decides *what* there is to write. A result carrying no records
        and an error is what stops the caller writing anything, which is where
        R6.1 and R5.8 meet: no artifact, therefore no cache entry.
        """
        result = run(["nonsense", "still nonsense"])

        assert result.failed
        assert result.records == ()
        assert result.checks == ()

    def test_abstention_is_written_and_cached(self):
        """Counter-example (row 4): the one where null is conforming output.

        `root_cause: null` with a reason validates, produces a record, and is
        cached like any other answer (R6.5).
        """
        abstained = json.dumps(
            {
                "document": "INC-4821",
                "fields": [
                    {
                        "field": "root_cause",
                        "value": None,
                        "reason": "not stated in document",
                        "confidence": "none",
                    }
                ],
            }
        )

        result = run([abstained])

        assert result.failed is False
        assert len(result.records) == 1

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param("", id="empty"),
            pytest.param("null", id="json-null"),
            pytest.param("[]", id="json-list"),
            pytest.param('{"fields": []}', id="missing-document"),
        ],
    )
    def test_shapes_that_are_not_a_stage_output_are_rejected(self, response: str):
        """The boundaries around "does not validate".

        Each is JSON-ish and none is a stage output. An empty response in
        particular would be easy to read as "no fields found", which is not the
        same as abstaining and must not be treated as it.
        """
        assert run([response, response]).failed


class TestTheCacheClaimsAreAssertedHere:
    """R6.1 rows 1 and 4 are about the cache, and this file never had one.

    Found by `/quality`. The test named `test_abstention_is_written_and_cached`
    asserted neither writing nor caching -- it exercised `run_stage`, which has
    no cache to look at. Row 1's negative half was in fact covered, but by
    R5.8's test, so R6.1 was leaning on another rule to prove its own claim.
    """

    def _run(self, tmp_path, responses: list[str]):
        from datetime import UTC, datetime

        from tests.pipelines import prompt_for

        from dossier.application.run import execute
        from dossier.domain.pipeline import PipelineConfig, StepConfig
        from dossier.infrastructure.cache import ArtifactCache

        config = PipelineConfig(
            name="incident-audit",
            sources=["incidents-manual"],
            model="anthropic:claude-sonnet-4-5-20250929",
            steps=[
                StepConfig(
                    id="extract",
                    prompt="prompts/01_extract.md",
                    input="documents",
                    mode="per_file",
                )
            ],
        )
        report = execute(
            workspace=tmp_path,
            pipeline=config,
            pipeline_hash="0e52dd18" * 8,
            documents={"INC-4821": "a3f9c1e2" * 8},
            document_text=STAGE_INPUTS,
            schemas={"extract": OUTPUT},
            prompts={"extract": prompt_for(["documents"])},
            model=FakeModelClient(responses=responses),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260806T142203Z-4f1a",
            started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
            dossier_version="0.1.0",
        )
        artifacts = [
            path
            for path in (tmp_path / ".dossier" / "cache").rglob("*")
            if path.is_file() and not path.name.endswith(".meta.json")
        ]
        return report, artifacts

    def test_output_that_never_validates_leaves_no_cache_entry(self, tmp_path):
        """Row 1: "no artifact on disk, no cache entry".

        Two invalid answers, so the document fails after its one retry (R6.2).
        Nothing is written, and the next run will ask again rather than serving
        a failure as though it were an answer.
        """
        report, artifacts = self._run(tmp_path, ["not json", "still not json"])

        assert report.failed == [("extract", "INC-4821")]
        assert artifacts == []

    def test_an_abstention_is_written_and_cached(self, tmp_path):
        """Row 4: the counter-example, asserted on the cache this time.

        `root_cause: null` with a reason is a conforming answer (R6.5), so it is
        an artifact like any other -- and a second run serves it without asking.
        """
        abstained = json.dumps(
            {
                "document": "INC-4821",
                "fields": [
                    {
                        "field": "root_cause",
                        "value": None,
                        "reason": "not stated in document",
                        "confidence": "none",
                    }
                ],
            }
        )

        report, artifacts = self._run(tmp_path, [abstained])

        assert report.failed == []
        assert len(artifacts) == 1
        assert b"not stated in document" in artifacts[0].read_bytes()
