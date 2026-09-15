"""R9.8 — a model endpoint's API key comes from the environment and never reaches
configuration, logs, ledger, manifest or provenance.

R1.8's promise, for model endpoints. A key is per machine (R9.2), is read from
the environment or `.env` by `dossier.config` alone (R9.11), and travels only as
far as the request header it is sent in. Everything a run writes down -- its
manifest, its cache entries and their provenance -- and every message it prints
is checked here for the key's value.

No socket is opened: `httpx.MockTransport` answers every request.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for, write_pipeline

from dossier.application.run import execute
from dossier.config.endpoints import EndpointUnset, endpoint_for
from dossier.config.load import ConfigError, load_pipeline
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.models.ollama import ModelRequestFailed, ollama
from dossier.infrastructure.models.registry import available_providers

KEY = "sk-4f1a-do-not-print"
DIGEST = "7f3c29a1" * 8
# `_fixtures.md` writes the digest as `7f3c29a1`; a real one carries 64 characters.
PINNED = f"ollama:qwen2.5:7b@sha256:{DIGEST}"
PASSTHROUGH = "https://ai.example.internal/ollama"
RUN_ID = "20260806T142203Z-4f1a"
TEXT = {"INC-4821": STAGE_INPUTS["INC-4821"]}


def _server(status: int = 200):
    """OpenWebUI's Ollama passthrough, answering chat with `status`."""
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

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5:7b", "digest": DIGEST}]}
            )
        if status != 200:
            return httpx.Response(status, json={"error": "unauthorized"})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": answer}})

    return httpx.MockTransport(handle)


def _endpoint():
    """The endpoint this machine reaches Ollama at, key included, as config reads it."""
    return endpoint_for(
        "ollama",
        default_url="http://localhost:11434",
        environ={"DOSSIER_OLLAMA_URL": PASSTHROUGH, "DOSSIER_OLLAMA_API_KEY": KEY},
    )


class TestModelAPIKeysAreNeverDisclosed:
    """R9.8 — the key reaches a request header and nothing else."""

    def test_a_refusal_names_the_url_and_the_status_and_not_the_key(self):
        """Example 1: the one with `DOSSIER_OLLAMA_API_KEY` set and OpenWebUI answering 401.

        The endpoint carries the key and does not show it either: an endpoint
        ends up in tracebacks, and its `repr` is what a traceback prints.
        """
        endpoint = _endpoint()
        client = ollama(
            PINNED, url=endpoint.url, api_key=endpoint.api_key, transport=_server(status=401)
        )

        with pytest.raises(ModelRequestFailed) as error:
            client.complete("x", schema=None)

        message = str(error.value)
        assert PASSTHROUGH in message
        assert "401" in message
        assert KEY not in message
        assert KEY not in repr(endpoint)

    def test_nothing_a_completed_run_writes_holds_the_key(self, tmp_path: Path):
        """Example 2: the one where a run completes with a key-bearing client.

        Every file the run wrote -- the manifest, every cache entry and its
        provenance record -- is read back and searched for the key's value.
        """
        endpoint = _endpoint()
        config = PipelineConfig(
            name="incident-audit",
            sources=["incidents-manual"],
            model=PINNED,
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

        report = execute(
            workspace=tmp_path,
            pipeline=config,
            pipeline_hash="0e52dd18" * 8,
            documents={"INC-4821": "a3f9c1e2" * 8},
            document_text=TEXT,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="6e0d4b27" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            model=ollama(
                PINNED, url=endpoint.url, api_key=endpoint.api_key, transport=_server()
            ),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id=RUN_ID,
            started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
            dossier_version="0.1.0",
        )

        written = [path for path in tmp_path.rglob("*") if path.is_file()]
        assert report.failed == []
        assert written, "the run wrote nothing, so the search below would prove nothing"
        assert [path for path in written if KEY.encode() in path.read_bytes()] == []

    def test_a_key_in_pipeline_yaml_is_refused_at_load_time(self, tmp_path: Path):
        """Example 3: the one where someone commits `api_key:` in `pipeline.yaml`.

        Refused naming the key it was written under -- and not echoing the value,
        which is the one thing the message must not repeat.
        """
        path = write_pipeline(tmp_path, model=PINNED)
        path.write_text(
            path.read_text(encoding="utf-8") + f"api_key: {KEY}\n", encoding="utf-8"
        )

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=available_providers())

        assert "api_key" in str(error.value)
        assert KEY not in str(error.value)

    def test_naming_a_variable_is_not_disclosing_its_value(self):
        """Counter-example (row 4): the one where an error names the variable.

        Allowed, and the useful thing to say: it tells the person what to set,
        and a variable's name is in `.env.example` for anyone to read. Only its
        value is a secret.
        """
        with pytest.raises(EndpointUnset) as error:
            endpoint_for("hf", default_url=None, environ={"DOSSIER_HF_API_KEY": KEY})

        assert "DOSSIER_HF_URL" in str(error.value)
        assert KEY not in str(error.value)
