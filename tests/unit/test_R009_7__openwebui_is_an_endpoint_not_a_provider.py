"""R9.7 — a model reached through OpenWebUI is keyed by its backend's pinned
identifier, never by an OpenWebUI model name.

OpenWebUI passes requests through to Ollama, to vLLM, or to a hosted provider.
An OpenWebUI model name is an alias its administrator can re-point, which is
exactly what R0.6 refuses; so OpenWebUI is where a model is reached, and the
identifier still names the backend's pinned form (spec 009).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

from dossier.config.endpoints import endpoint_for
from dossier.config.load import ConfigError, load_pipeline
from dossier.domain.keys import ArtifactInput, StageInputs, cache_key
from dossier.domain.model_id import check_pinned
from dossier.infrastructure.models.registry import available_providers

# `_fixtures.md` writes these as 8 characters; a real identifier carries them all.
OLLAMA = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
HF = "hf:Qwen/Qwen2.5-7B-Instruct@" + "1c0f8e6b" * 5
OPENWEBUI_OLLAMA = "https://ai.example.internal/ollama"


def _key(model: str) -> str:
    return cache_key(
        StageInputs(
            step="extract",
            prompt=ArtifactInput(
                role="prompt", path="prompts/01_extract.md", hash="0e52dd18" * 8
            ),
            model=model,
        )
    )


class TestOpenWebUIIsAnEndpointNotAProvider:
    """R9.7 — OpenWebUI is where a model is reached; the key names what answers."""

    def test_ollama_through_openwebui_has_the_keys_of_ollama_reached_directly(self):
        """Example 1: the one reached through `https://ai.example.internal/ollama`.

        The two endpoints differ and the keys cannot: a stage key has no field
        an endpoint could go in, only the pinned identifier (R5.3 row 4).
        """
        direct = endpoint_for("ollama", default_url="http://localhost:11434", environ={})
        through = endpoint_for(
            "ollama",
            default_url="http://localhost:11434",
            environ={"DOSSIER_OLLAMA_URL": OPENWEBUI_OLLAMA},
        )

        assert direct.url != through.url
        assert not set(StageInputs.model_fields) & {"url", "endpoint", "base_url", "host"}
        assert _key(OLLAMA) == _key(OLLAMA)

    def test_an_openwebui_model_name_is_refused(self, tmp_path: Path):
        """Example 2: the one where `model: openwebui:my-qwen` names an alias.

        No package provides `openwebui`, so it is refused at load (R9.1) --
        and none should: its administrator can re-point `my-qwen` at any model.
        """
        path = write_pipeline(tmp_path, model="openwebui:my-qwen")

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=available_providers())

        assert "openwebui" in str(error.value)

    def test_a_backend_url_may_point_at_openwebui(self):
        """Counter-example (row 3): the one where `DOSSIER_HF_URL` is OpenWebUI's route.

        Allowed. The identifier is still vLLM's pinned form; only where it is
        reached has changed.
        """
        check_pinned(HF)
        endpoint = endpoint_for(
            "hf", default_url=None, environ={"DOSSIER_HF_URL": "http://localhost:8080/api"}
        )

        assert endpoint.url == "http://localhost:8080/api"
