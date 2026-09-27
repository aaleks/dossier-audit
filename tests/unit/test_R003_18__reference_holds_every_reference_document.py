"""R3.18 rows 1-3 — `{{reference}}` holds every reference document, each under
its own key in key order, whatever the step's mode.

Run through `execute`, because what a placeholder holds is decided where a
call's inputs are rendered, for every mode alike. The reference documents are
handed in apart from the audited ones, as the run reads them from the
`reference:` sources. The model is a fake that records every prompt (R0.1).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.pipelines import prompt_for

from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
INCIDENTS = {
    "INC-4821": "Finance confirmed a total exposure CHF 48'200.",
    "INC-4822": "The payment gateway timed out for two hours.",
}
# Handed in out of key order, so key order is something the rendering does.
PROCEDURES = {
    "OPS-116": "Hold a review within 5 days.",
    "OPS-114": "Escalate within 30 minutes.",
    "OPS-115": "Notify customers within 4 hours.",
}
SHOWN = re.compile(r'<document key="([^"]+)">')


def _section(prompt: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", prompt, re.DOTALL)
    assert match is not None, f"no <{tag}> in the prompt"
    return match.group(1)


class Model:
    """Answers every call with nothing extracted, and remembers each prompt."""

    model_id = MODEL

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        self.prompts.append(prompt)
        audited = SHOWN.findall(_section(prompt, "source_document"))
        return json.dumps({"document": audited[0], "fields": []})


def _run(tmp_path: Path, *, mode: str) -> Model:
    """One `verify` step over the two incidents, reading the three procedures."""
    model = Model()
    execute(
        workspace=tmp_path,
        pipeline=PipelineConfig(
            name="incident-audit",
            sources=["incidents-jira"],
            reference=["procedures-confluence"],
            model=MODEL,
            steps=[
                StepConfig(
                    id="verify",
                    prompt="prompts/verify.md",
                    input=["documents", "reference"],
                    mode=mode,
                )
            ],
        ),
        pipeline_hash="0e52dd18" * 8,
        documents={key: sha256(text.encode()).hexdigest() for key, text in INCIDENTS.items()},
        document_text=INCIDENTS,
        reference_content={"markdown": PROCEDURES},
        schemas={"verify": SCHEMA},
        prompts={"verify": prompt_for(["documents", "reference"])},
        model=model,
        cache=ArtifactCache(tmp_path, namespace="stage"),
        run_id="20260806T142203Z-4f1a",
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
    )
    return model


class TestReferenceHoldsEveryReferenceDocument:
    """R3.18 — context is the same for every document it is context for."""

    def test_a_per_file_call_holds_every_procedure_in_key_order(self, tmp_path: Path):
        """Row 1: the one where `INC-4821` is verified against the procedures."""
        model = _run(tmp_path, mode="per_file")

        held = _section(model.prompts[0], "procedure")
        assert SHOWN.findall(held) == ["OPS-114", "OPS-115", "OPS-116"]
        assert '<document key="OPS-114">Escalate within 30 minutes.</document>' in held

    def test_every_call_holds_the_same_procedures(self, tmp_path: Path):
        """Row 2: the one where `INC-4822` is shown what `INC-4821` was."""
        model = _run(tmp_path, mode="per_file")

        first, second = (_section(prompt, "procedure") for prompt in model.prompts)
        assert first == second

    def test_an_aggregate_call_holds_them_once(self, tmp_path: Path):
        """Row 3: the one where one call reads the whole set."""
        model = _run(tmp_path, mode="aggregate")

        (prompt,) = model.prompts
        assert SHOWN.findall(_section(prompt, "procedure")) == ["OPS-114", "OPS-115", "OPS-116"]
