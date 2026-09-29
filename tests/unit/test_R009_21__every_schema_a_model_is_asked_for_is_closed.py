"""R9.21 — every JSON schema a model is asked to answer in is closed: each object
in it sets `additionalProperties` to false.

Anthropic refuses an open schema with `400 Bad Request` before the model reads
a word. The step's generated schema was closed and the judge's was not, so on
2026-09-29 `claude-haiku-4-5-20251001` answered every page of exercise 10 and
refused every judge call.

Asserted on what the model client is handed, through a `FakeModelClient` that
keeps each call's schema; and on the schema `json_schema` generates from a
declaration, which is the one a step is handed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.eval import judged
from dossier.application.run import RunInputs, execute
from dossier.domain.fields import OutputSchema, json_schema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.scoring import FieldKind

SUPPORTED = json.dumps({"supported": True, "evidence": "the Root cause section"})


def _objects(schema: object) -> list[dict]:
    """Every object a schema describes, however deeply it is nested."""
    found: list[dict] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            found.append(schema)
        for value in schema.values():
            found.extend(_objects(value))
    elif isinstance(schema, list):
        for value in schema:
            found.extend(_objects(value))
    return found


class TestEverySchemaAModelIsAskedForIsClosed:
    """R9.21 — each object in a schema a model is handed sets `additionalProperties` false."""

    def test_the_judge_is_handed_a_closed_verdict(self):
        """Row 1 — the one Anthropic refused: a verdict with room for any key."""
        judge = FakeModelClient(responses=[SUPPORTED])

        judged(
            judge,
            rubric="Is the root cause supported by the document?",
            document="INC-4821",
            text=ISSUES["INC-4821"],
            answer="A payments-api retry storm exhausted the ledger connection pool.",
        )

        assert judge.calls[0]["schema"] == {
            "type": "object",
            "properties": {"supported": {"type": "boolean"}, "evidence": {"type": "string"}},
            "required": ["supported"],
            "additionalProperties": False,
        }

    def test_a_step_is_handed_a_schema_closed_at_every_level(self):
        """Row 2 — the one already closed: the answer, its records and their evidence."""
        schema = json_schema(
            {
                "incident_date": FieldKind.DATE,
                "severity": FieldKind.ENUM,
                "root_cause": FieldKind.FREE_TEXT,
            },
            # The enum's own record is closed too (R6.25).
            values={"severity": ("minor", "major", "critical")},
        )

        objects = _objects(schema)
        assert {entry.get("title") for entry in objects} >= {
            "StageOutput",
            "FieldRecord",
            "Evidence",
        }
        assert all(entry.get("additionalProperties") is False for entry in objects), objects

    def test_a_step_with_no_output_is_handed_no_schema(self, tmp_path: Path):
        """Row 3, counter-example — the one whose prose nothing constrains (R0.14 row 5)."""
        from dossier.infrastructure.cache import ArtifactCache

        answer = json.dumps({"document": "INC-4821", "fields": []})
        model = FakeModelClient(responses=[answer, "One incident, nothing extracted."])
        execute(
            RunInputs(
                pipeline=PipelineConfig(
                    name="incident-audit",
                    sources=["incidents-jira"],
                    model="anthropic:claude-sonnet-4-5-20250929",
                    steps=[
                        StepConfig(
                            id="extract",
                            prompt="prompts/extract.md",
                            input="documents",
                            mode="per_file",
                            output="schemas/incident.yaml",
                        ),
                        StepConfig(
                            id="report",
                            prompt="prompts/report.md",
                            input="extract",
                            mode="aggregate",
                        ),
                    ],
                ),
                pipeline_hash="6e0d4b27" * 8,
                schemas={
                    "extract": OutputSchema(
                        schema=json_schema({"root_cause": FieldKind.FREE_TEXT}, values={}),
                        declaration_hash="d24c86e1" * 8,
                    ),
                    "report": None,
                },
                prompts={
                    "extract": prompt_for(["documents"]),
                    "report": prompt_for(["extract"]),
                },
                documents={"INC-4821": "a3f9c1e2" * 8},
                document_text={"INC-4821": ISSUES["INC-4821"]},
            ),
            workspace=tmp_path,
            model=model,
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260929T062805Z-3c0e",
            started_at=datetime(2026, 9, 29, 6, 28, 5, tzinfo=UTC),
            dossier_version="0.1.0",
        )

        assert model.call_count == 2
        assert model.calls[0]["schema"] is not None
        assert model.calls[1]["schema"] is None
