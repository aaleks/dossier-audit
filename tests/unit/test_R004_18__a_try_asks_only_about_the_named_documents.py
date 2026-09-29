"""R4.18 — `dossier run --doc KEY` asks every step only about the named documents.

A try is asked what a full run would ask about the named documents, and
nothing about any other. Run through `execute`, whose `tried` is what `--doc`
names, with a `FakeModelClient` that **counts calls** and keeps each prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for
from tests.scoring_example import FIFTH_ISSUE, ISSUES

from dossier.application.run import RunInputs, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig

TEXT = {**ISSUES, **FIFTH_ISSUE}
DOCUMENTS = tuple(sorted(TEXT))
# `_fixtures.md`'s contracts: ACME-2024 is a master and two amendments, and
# GLOBEX-2023 a group of one.
CONTRACTS = {
    "ACME-2024/amendment-1.pdf": "Amendment 1 changes the invoicing address.",
    "ACME-2024/amendment-3.pdf": "Amendment 3 extends the term to 2027-03-31.",
    "ACME-2024/master.pdf": "Liability is capped at EUR 2,000,000.",
    "GLOBEX-2023/master.pdf": "The term ends 2026-12-31.",
}


def _snapshot(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _run(
    workspace: Path,
    *,
    tried: tuple[str, ...] | None,
    mode: str = "per_file",
    text: dict[str, str] = TEXT,
) -> FakeModelClient:
    """`extract` over `text`, in `mode`; the model, having been asked."""
    from dossier.infrastructure.cache import ArtifactCache

    model = FakeModelClient(
        responses=[json.dumps({"document": key, "fields": []}) for key in sorted(text)]
    )
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
                        mode=mode,
                        output="schemas/incident.yaml",
                    )
                ],
            ),
            pipeline_hash="6e0d4b27" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            documents={key: _snapshot(body) for key, body in text.items()},
            document_text=text,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id="20260929T100000Z-1a2b",
        started_at=datetime(2026, 9, 29, 10, 0, tzinfo=UTC),
        dossier_version="0.1.0",
        tried=tried,
    )
    return model


def _about(model: FakeModelClient) -> list[list[str]]:
    """Which of the five documents each call's prompt holds, call by call."""
    return [
        [key for key in DOCUMENTS if TEXT[key] in str(call["prompt"])] for call in model.calls
    ]


def _shown(model: FakeModelClient) -> list[list[str]]:
    """The documents each call was handed, each wrapped under its own key (R3.13)."""
    wrapped = re.compile(r'<document key="([^"]+)">')
    return [wrapped.findall(str(call["prompt"])) for call in model.calls]


class TestATryAsksOnlyAboutTheNamedDocuments:
    """R4.18 — `dossier run --doc KEY` asks every step only about the named documents."""

    def test_one_named_document_is_the_one_asked_about(self, tmp_path: Path):
        """Row 1 — the one where four of five incidents are left alone."""
        model = _run(tmp_path, tried=("INC-4821",))

        assert model.call_count == 1
        assert _about(model) == [["INC-4821"]]

    def test_a_named_member_is_asked_about_with_its_whole_group(self, tmp_path: Path):
        """Row 4 — the one where an amendment brings its master and its sibling.

        A `per_group` step's unit is the group (R3.15). Asked about amendment 3
        alone, it would be a different question from the one a full run asks
        (R4.15), and its answer a different key's.
        """
        model = _run(
            tmp_path, tried=("ACME-2024/amendment-3.pdf",), mode="per_group", text=CONTRACTS
        )

        assert _shown(model) == [
            ["ACME-2024/amendment-1.pdf", "ACME-2024/amendment-3.pdf", "ACME-2024/master.pdf"]
        ]
