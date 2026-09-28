"""R9.1 — a model whose provider no installed package provides is refused at load time.

The provider is what precedes the first `:`. A provider is a package declaring a
`dossier.models` entry point (spec 009), so a model naming one nobody installed
is found before any work begins -- not at the first cache miss an hour into a
run.

`config/` may import only `domain/`, so the installed providers are handed in:
the CLI reads them from the entry points, and a test passes a set.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for, write_pipeline

from dossier.application.manifest import Manifest
from dossier.application.run import RunInputs, execute, replay
from dossier.config.load import ConfigError, load_pipeline
from dossier.domain.fields import OutputSchema
from dossier.domain.model_id import provider_of
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

PROVIDERS = frozenset({"anthropic", "hf", "ollama"})
# `_fixtures.md` writes it as `7f3c29a1`; a real digest carries all 64 characters.
OLLAMA = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
RUN_ID = "20260806T142203Z-4f1a"
TEXT = {"INC-4821": STAGE_INPUTS["INC-4821"]}


class TestAnUnknownProviderIsRefusedAtLoadTime:
    """R9.1 — a model's provider is installed, or nothing runs."""

    def test_an_anthropic_model_resolves_to_its_provider(self, tmp_path: Path):
        """Example 1: the one where `anthropic:` is installed and the model loads."""
        model = "anthropic:claude-sonnet-4-5-20250929"
        path = write_pipeline(tmp_path, model=model)

        config = load_pipeline(path, providers=PROVIDERS)

        assert config.model == model
        assert provider_of(config.model) == "anthropic"

    def test_an_ollama_tags_own_colon_is_not_a_provider_boundary(self, tmp_path: Path):
        """Example 2: the one where `qwen2.5:7b` has a colon of its own.

        The provider is what precedes the *first* colon. Split on the last and
        the provider would read `ollama:qwen2.5`, which nobody installed.
        """
        path = write_pipeline(tmp_path, model=OLLAMA)

        config = load_pipeline(path, providers=PROVIDERS)

        assert provider_of(config.model) == "ollama"

    def test_a_third_party_provider_loads_with_no_edit_to_dossier(self, tmp_path: Path):
        """Example 3: the one where a package declares `lmstudio`.

        Installed means declared in the entry point group, and nothing else: the
        core has no list of providers to extend.
        """
        path = write_pipeline(tmp_path, model="lmstudio:qwen2.5-7b-instruct")

        config = load_pipeline(path, providers=PROVIDERS | {"lmstudio"})

        assert provider_of(config.model) == "lmstudio"

    def test_a_replay_is_not_refused_where_no_provider_is_installed(
        self, tmp_path: Path, monkeypatch
    ):
        """Counter-example (row 5): the one replayed on a machine with no Ollama.

        A replay asks no model (R4.7, R0.9), so refusing it for want of a
        provider would make a past audit unreproducible over a client it never
        needs. The model registry is emptied before replaying, so a replay that
        consulted it would fail.
        """
        config = PipelineConfig(
            name="incident-audit",
            sources=["incidents-manual"],
            model=OLLAMA,
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
            model=FakeModelClient(responses=[answer], model_id=OLLAMA),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id=RUN_ID,
            started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
            dossier_version="0.1.0",
        )
        manifest = Manifest.read(tmp_path / "runs" / RUN_ID / "manifest.json")

        import dossier.infrastructure.models.registry as registry

        monkeypatch.setattr(registry, "entry_points", lambda group: [])
        assert registry.available_providers() == []

        report = replay(
            manifest=manifest,
            document_text=TEXT,
            cache=ArtifactCache(tmp_path, namespace="stage"),
        )

        assert len(report.steps[0].served_from_cache) == 1

    def test_a_provider_nothing_provides_is_refused_naming_those_available(
        self, tmp_path: Path
    ):
        """Example 4: the one where `mistral:` names a provider no package installed.

        Refused at load, naming the file, the line and the providers that are
        available -- so the fix, installing one or naming another, is on screen.
        """
        path = write_pipeline(tmp_path, model="mistral:mistral-large-2411")

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        message = str(error.value)
        assert "pipeline.yaml" in message
        assert "line 2" in message
        assert "mistral" in message
        for provider in PROVIDERS:
            assert provider in message
