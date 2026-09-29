"""R4.21 — a try's answers are cached under the keys a full run would use, so
the next full run is served them.

What a try asks about is asked as a full run would ask it (spec 005). Nothing
about it being a try reaches a key, so its answers are never wasted.

Run through `execute`, whose `tried` is what `--doc` names, over one cache,
with a `FakeModelClient` per command that **counts calls**.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for
from tests.scoring_example import FIFTH_ISSUE, ISSUES

from dossier.application.run import RunInputs, RunReport, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig

TEXT = {**ISSUES, **FIFTH_ISSUE}
PROMPT = prompt_for(["documents"])
EDITED = PROMPT + "\nThe resolution date is the day the fix was confirmed.\n"


def _execute(
    workspace: Path, run_id: str, *, tried: tuple[str, ...] | None = None, prompt: str = PROMPT
) -> tuple[FakeModelClient, RunReport]:
    """`extract` per_file over the five incidents; the model it asked, and the report."""
    from dossier.infrastructure.cache import ArtifactCache

    model = FakeModelClient(
        responses=[json.dumps({"document": key, "fields": []}) for key in sorted(TEXT)]
    )
    report = execute(
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
                    )
                ],
            ),
            pipeline_hash="6e0d4b27" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                )
            },
            prompts={"extract": prompt},
            documents={key: sha256(text.encode()).hexdigest() for key, text in TEXT.items()},
            document_text=TEXT,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime.strptime(run_id[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
        dossier_version="0.1.0",
        tried=tried,
    )
    return model, report


def _served(report: RunReport) -> list[str]:
    (step,) = report.steps
    return [result.document for result in step.served_from_cache]


class TestATrysAnswersServeTheNextFullRun:
    """R4.21 — a try's answers are cached under a full run's keys."""

    def test_the_full_run_after_a_try_is_served_its_answer(self, tmp_path: Path):
        """Row 1 — the one where the try paid for INC-4821, and the run does not again."""
        _execute(tmp_path, "20260929T100000Z-1a2b", tried=("INC-4821",))

        model, report = _execute(tmp_path, "20260929T110000Z-4f1a")

        assert model.call_count == 4
        assert _served(report) == ["INC-4821"]

    def test_a_try_after_a_full_run_is_served_the_runs_answer(self, tmp_path: Path):
        """Row 2 — the one where the try asks nothing, the run having asked already."""
        _execute(tmp_path, "20260806T142203Z-4f1a")

        model, report = _execute(tmp_path, "20260929T100000Z-1a2b", tried=("INC-4821",))

        assert model.call_count == 0
        assert _served(report) == ["INC-4821"]

    def test_a_prompt_edited_since_the_try_is_asked_again(self, tmp_path: Path):
        """Row 3, counter-example — the one where the prompt is in the key, whoever asked."""
        _execute(tmp_path, "20260929T100000Z-1a2b", tried=("INC-4821",))

        model, report = _execute(tmp_path, "20260929T110000Z-4f1a", prompt=EDITED)

        assert model.call_count == 5
        assert _served(report) == []
