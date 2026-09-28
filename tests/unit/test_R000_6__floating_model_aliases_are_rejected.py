"""R0.6 — model identifiers are pinned exactly, and floating aliases are rejected at load time.

An id is pinned when it is in its provider's immutable form -- for `anthropic`,
a dated snapshot -- or when `dossier.domain.model_id` names it as an id the
provider documents as fixed. The decision is made here, once; the loader only
adds where it was written (R3.4).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.manifest import Manifest
from dossier.application.run import RunInputs, execute, replay
from dossier.domain.fields import OutputSchema
from dossier.domain.model_id import check_pinned
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

RUN_ID = "20260806T142203Z-4f1a"
TEXT = {"INC-4821": STAGE_INPUTS["INC-4821"]}


class TestFloatingModelAliasesAreRejected:
    """R0.6 — a model names an exact, immutable version, or nothing runs."""

    def test_a_dated_snapshot_is_accepted(self):
        """Example 1: the one where the model is exactly one snapshot."""
        check_pinned("anthropic:claude-sonnet-4-5-20250929")

    def test_a_family_alias_is_refused_naming_it(self):
        """Example 2: the one where `claude-sonnet-4-5` moves to each new snapshot.

        Naming the file and the line is the loader's half, and R3.4 proves it.
        What is decided here is that the id is an alias, and which id it was.
        """
        with pytest.raises(ValueError) as error:
            check_pinned("anthropic:claude-sonnet-4-5")

        assert "anthropic:claude-sonnet-4-5" in str(error.value)

    def test_latest_is_refused(self):
        """Example 3: the one where the alias says out loud that it moves."""
        with pytest.raises(ValueError):
            check_pinned("anthropic:claude-sonnet-latest")

    def test_an_undated_id_the_provider_documents_as_fixed_is_accepted(self):
        """Example 5: the one where `claude-opus-5` has no date and is still pinned.

        A date suffix is how most anthropic ids are pinned, not what pinned means.
        """
        check_pinned("anthropic:claude-opus-5")

    def test_a_replay_uses_the_recorded_identifier_as_it_is(self, tmp_path: Path, monkeypatch):
        """Counter-example (row 4): the one where the check already happened.

        A replay reads the model from the manifest and asks no model. Refusing it
        now -- because the list changed, say -- would make a past audit
        unreproducible over a rule it already passed when it was resolved (R4.7).
        """
        model = "anthropic:claude-opus-5"
        config = PipelineConfig(
            name="incident-audit",
            sources=["incidents-manual"],
            model=model,
            steps=[
                StepConfig(
                    id="extract",
                    prompt="prompts/01_extract.md",
                    input="documents",
                    mode="per_file",
                    output="schemas/incident.yaml",
                )
            ],
        )
        answer = json.dumps(
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
        execute(
            RunInputs(
                pipeline=config,
                pipeline_hash="0e52dd18" * 8,
                schemas={
                    "extract": OutputSchema(
                        schema={"type": "object"}, declaration_hash="6e0d4b27" * 8
                    )
                },
                prompts={"extract": prompt_for(["documents"])},
                documents={"INC-4821": "a3f9c1e2" * 8},
                document_text=TEXT,
            ),
            workspace=tmp_path,
            model=FakeModelClient(responses=[answer], model_id=model),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id=RUN_ID,
            started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
            dossier_version="0.1.0",
        )
        manifest = Manifest.read(tmp_path / "runs" / RUN_ID / "manifest.json")

        # From here on, no id would pass the check -- so a replay that consulted
        # it would fail.
        import dossier.config.load as load
        import dossier.domain.model_id as model_id

        def refuse(identifier: str) -> None:
            raise ValueError(f"model {identifier!r} refused")

        monkeypatch.setattr(model_id, "check_pinned", refuse)
        monkeypatch.setattr(load, "check_pinned", refuse)

        report = replay(
            manifest=manifest,
            document_text=TEXT,
            cache=ArtifactCache(tmp_path, namespace="stage"),
        )

        assert manifest.plan.model == model
        assert len(report.steps[0].served_from_cache) == 1
