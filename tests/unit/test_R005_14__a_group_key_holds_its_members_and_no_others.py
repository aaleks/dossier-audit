"""R5.14 — a `per_group` step's key holds every member's inputs and no other document's.

R5.10's promise with the group as the unit: one amendment filed asks about one
contract again, and not four hundred. The key is the stage key of spec 005 over
the input values a group's call is handed -- its members, each wrapped under its
own key (R3.13) -- so a member added, replaced or removed moves its group's key,
and a document in another group moves nothing here.

Two runs through `execute`, the second after the corpus changed, counting the
calls the second one makes and which members each was shown. The model is a
fake that answers anything and records what it saw (R0.1).
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
CONTRACTS = {
    "ACME-2024/amendment-1.pdf": "Amendment 1 changes the invoicing address.",
    "ACME-2024/amendment-3.pdf": "Amendment 3 extends the term to 2027-03-31.",
    "ACME-2024/master.pdf": "Liability is capped at EUR 2,000,000.",
    "GLOBEX-2023/master.pdf": "The term ends 2026-12-31.",
}


class Model:
    """Answers every call, and remembers which documents each one was shown."""

    model_id = MODEL

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        shown = re.findall(r'<document key="([^"]+)">', prompt)
        self.calls.append(shown)
        return json.dumps({"document": shown[0], "fields": []})


def _run(workspace: Path, text: dict[str, str], model: Model, *, run_id: str):
    config = PipelineConfig(
        name="contract-renewal",
        sources=["contracts"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract", prompt="prompts/extract.md", input="documents", mode="per_group"
            )
        ],
    )
    return execute(
        workspace=workspace,
        pipeline=config,
        pipeline_hash="0e52dd18" * 8,
        # A snapshot address per document that moves with its text, as a
        # content hash does (R2.6).
        documents={key: sha256(body.encode()).hexdigest() for key, body in text.items()},
        document_text=text,
        schemas={"extract": SCHEMA},
        prompts={"extract": prompt_for(["documents"])},
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
    )


def _after(workspace: Path, changed: dict[str, str]) -> Model:
    """Run over `CONTRACTS`, then over `changed`, and return the second run's model."""
    _run(workspace, CONTRACTS, Model(), run_id="20260806T142203Z-4f1a")
    second = Model()
    _run(workspace, changed, second, run_id="20260907T090000Z-bbbb")
    return second


class TestAGroupKeyHoldsItsMembersAndNoOthers:
    """R5.14 — a change moves its own group's key, and no other group's."""

    def test_an_amendment_filed_asks_about_its_contract_alone(self, tmp_path: Path):
        """Row 1: the one where amendment 4 is filed after a first run.

        One call, for ACME, shown all four of its members. GLOBEX is served from
        cache: nothing it was asked about has changed.
        """
        amendment = "ACME-2024/amendment-4.pdf"
        second = _after(tmp_path, {**CONTRACTS, amendment: "Amendment 4 adds a site."})

        assert second.calls == [
            [
                "ACME-2024/amendment-1.pdf",
                "ACME-2024/amendment-3.pdf",
                amendment,
                "ACME-2024/master.pdf",
            ]
        ]

    def test_a_member_replaced_moves_its_groups_key(self, tmp_path: Path):
        """Row 2: the one with the same three members and new words in one.

        Amendment 3 re-issued with a different date is a new snapshot (R2.6),
        and the contract is asked about again, though no member came or went.
        """
        replaced = {**CONTRACTS, "ACME-2024/amendment-3.pdf": "The term ends 2028-03-31."}

        second = _after(tmp_path, replaced)

        assert [len(shown) for shown in second.calls] == [3]
        assert second.calls[0][0].startswith("ACME-2024/")

    def test_a_member_removed_asks_again_without_it(self, tmp_path: Path):
        """Row 3: the one where amendment 3 is tombstoned."""
        removed = {k: v for k, v in CONTRACTS.items() if k != "ACME-2024/amendment-3.pdf"}

        second = _after(tmp_path, removed)

        assert second.calls == [["ACME-2024/amendment-1.pdf", "ACME-2024/master.pdf"]]

    def test_a_document_in_another_group_moves_nothing_here(self, tmp_path: Path):
        """Row 4, a counter-example: the one where GLOBEX gains an amendment.

        GLOBEX is asked again, and ACME is not: no member of ACME changed, so
        neither did any byte of its key.
        """
        added = {**CONTRACTS, "GLOBEX-2023/amendment-1.pdf": "Amendment 1 adds a site."}

        second = _after(tmp_path, added)

        assert second.calls == [["GLOBEX-2023/amendment-1.pdf", "GLOBEX-2023/master.pdf"]]
