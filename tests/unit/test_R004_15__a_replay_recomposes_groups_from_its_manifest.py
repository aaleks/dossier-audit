"""R4.15 — a replay recomposes each group from the documents its manifest pins,
never from what is held now.

A group is its members, and a replay reproduces the call a run made, not the
call it would make today. The manifest pins every document by key (R4.4), and a
group is computed from keys alone (R3.15), so the groups a run asked about are
recomposed from the manifest without being recorded anywhere new. A document
synced since is invisible to the replay, as a changed prompt is (R4.7).

A replay takes no model at all, so "no model call" is structural here: every
answer comes from the cache entry the run wrote, or the replay raises.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.pipelines import prompt_for

from dossier.application.manifest import Manifest
from dossier.application.run import RunInputs, execute, replay
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

MODEL = "anthropic:claude-sonnet-4-5-20250929"
CONTRACTS = {
    "ACME-2024/amendment-1.pdf": "Amendment 1 changes the invoicing address.",
    "ACME-2024/amendment-3.pdf": "Amendment 3 extends the term to 2027-03-31.",
    "ACME-2024/master.pdf": "Liability is capped at EUR 2,000,000.",
    "GLOBEX-2023/master.pdf": "The term ends 2026-12-31.",
}
AMENDMENT_4 = "ACME-2024/amendment-4.pdf"


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
        RunInputs(
            pipeline=config,
            pipeline_hash="0e52dd18" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="6e0d4b27" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            documents={key: sha256(body.encode()).hexdigest() for key, body in text.items()},
            document_text=text,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
    )


class TestAReplayRecomposesGroupsFromItsManifest:
    """R4.15 — the groups a run asked about, rebuilt from its manifest."""

    def test_a_group_run_replays_group_by_group(self, tmp_path: Path):
        """Row 1: the one where both contracts come back from cache, byte for byte."""
        ran = _run(tmp_path, CONTRACTS, Model(), run_id="20260806T142203Z-4f1a")
        original = tmp_path / "runs" / "20260806T142203Z-4f1a" / "extract"
        destination = tmp_path / "replayed"

        replayed = replay(
            manifest=Manifest.read(ran.manifest_path),
            document_text=CONTRACTS,
            cache=ArtifactCache(tmp_path, namespace="stage"),
            destination=destination,
        )

        (step,) = replayed.steps
        assert [result.document for result in step.results] == ["ACME-2024", "GLOBEX-2023"]
        for group in ("ACME-2024", "GLOBEX-2023"):
            assert (destination / "extract" / f"{group}.json").read_bytes() == (
                original / f"{group}.json"
            ).read_bytes()

    def test_a_document_held_since_is_not_a_member_of_the_replay(self, tmp_path: Path):
        """Row 2: the one where amendment 4 was synced after the run.

        The workspace holds it now, and the replay is handed its text. The run
        was asked about three ACME documents, so the replay is too: were it to
        take membership from what is held, the key would be one the run never
        wrote, and the replay would stop.
        """
        ran = _run(tmp_path, CONTRACTS, Model(), run_id="20260806T142203Z-4f1a")
        held_now = {**CONTRACTS, AMENDMENT_4: "Amendment 4 adds a site."}

        replayed = replay(
            manifest=Manifest.read(ran.manifest_path),
            document_text=held_now,
            cache=ArtifactCache(tmp_path, namespace="stage"),
        )

        # Found at all is the assertion: the key held three members, as the
        # run's did. Four would be a key no run wrote, and the replay raises.
        assert [r.document for r in replayed.steps[0].results] == ["ACME-2024", "GLOBEX-2023"]

    def test_a_new_run_after_the_sync_asks_about_four(self, tmp_path: Path):
        """Row 3, a counter-example: the one that is a run, not a replay.

        A run reads what is held: four members, a new key, one call (R5.14).
        """
        _run(tmp_path, CONTRACTS, Model(), run_id="20260806T142203Z-4f1a")
        model = Model()

        _run(
            tmp_path,
            {**CONTRACTS, AMENDMENT_4: "Amendment 4 adds a site."},
            model,
            run_id="20260907T090000Z-bbbb",
        )

        assert model.calls == [
            [
                "ACME-2024/amendment-1.pdf",
                "ACME-2024/amendment-3.pdf",
                AMENDMENT_4,
                "ACME-2024/master.pdf",
            ]
        ]
