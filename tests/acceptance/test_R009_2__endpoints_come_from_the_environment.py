"""R9.2 — where a provider is reached is read from the environment, never from
committed configuration.

`model:` says what answers; where it is served is per machine. A stage key holds
the identifier and not the endpoint (R5.3 row 4), so one pipeline shares one
cache between a laptop and a GPU server -- and an endpoint written into
`pipeline.yaml` would be a per-machine fact committed as if it were part of the
pipeline.

Observed from the CLI, because no single component makes it true: `config` reads
the variable, the provider an installed package declares builds a client from
it, and `run` must not ask for either until its first cache miss. A run served
entirely from cache reaches no model, so it needs no endpoint (R0.9).

The provider is registered the way an installed package would register it
(R9.1) and records every endpoint it builds a client for. Nothing here opens a
socket.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import register_provider
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
# `_fixtures.md` writes these as 8 characters; a real identifier carries them all.
OLLAMA = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
HF = "hf:Qwen/Qwen2.5-7B-Instruct@" + "1c0f8e6b" * 5
FIELDS = ("loss_amount", "resolution_date", "severity", "affected_systems", "root_cause")


class Provider:
    """A provider package's factory: builds a client, and remembers where for.

    Its clients abstain on every field, which is a valid answer for any document
    (R6.5) -- this rule is about where the model is reached, not what it says.
    Calls are counted, because rows 2 and 5 are claims about how many happened.
    """

    def __init__(self) -> None:
        self.built: list[str] = []
        self.calls = 0

    def __call__(self, model_id: str, *, url: str, api_key: str | None = None):
        self.built.append(url)
        return _Client(model_id, self)


class _Client:
    def __init__(self, model_id: str, provider: Provider) -> None:
        self.model_id = model_id
        self._provider = provider

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self._provider.calls += 1
        return json.dumps(
            {
                "document": "any",
                "fields": [
                    {"field": field, "value": None, "reason": "not stated in document"}
                    for field in FIELDS
                ],
            }
        )


@pytest.fixture
def ollama(monkeypatch) -> Provider:
    """Ollama, whose default is `http://localhost:11434` (spec 009)."""
    provider = Provider()
    register_provider(monkeypatch, "ollama", provider, default_url="http://localhost:11434")
    return provider


@pytest.fixture
def hf(monkeypatch) -> Provider:
    """A model served by vLLM, which has no default endpoint (spec 009)."""
    provider = Provider()
    register_provider(monkeypatch, "hf", provider)
    return provider


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _synced(workspace: Path, monkeypatch, model: str) -> None:
    """The fixture folder's documents, held and ready to run over `model`."""
    write_pipeline(workspace, model=model)
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output


class TestEndpointsComeFromTheEnvironment:
    """R9.2 — where a provider is reached is read from the environment, never from
    committed configuration."""

    def test_requests_go_to_the_url_the_environment_names(
        self, workspace: Path, monkeypatch, ollama: Provider
    ):
        """Example 1: the one where `DOSSIER_OLLAMA_URL` points at a GPU server."""
        monkeypatch.setenv("DOSSIER_OLLAMA_URL", "http://gpu-01:11434")
        _synced(workspace, monkeypatch, OLLAMA)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert ollama.built == ["http://gpu-01:11434"]
        assert ollama.calls > 0

    def test_two_machines_reaching_one_model_share_one_cache(
        self, workspace: Path, monkeypatch, ollama: Provider
    ):
        """Example 2: the one where the same identifier is reached at two URLs.

        The endpoint is in no key, so the second machine finds every answer the
        first one paid for (R5.3 row 4).
        """
        monkeypatch.setenv("DOSSIER_OLLAMA_URL", "http://localhost:11434")
        _synced(workspace, monkeypatch, OLLAMA)
        first = _cli(workspace, monkeypatch, "run", PIPELINE)
        assert first.exit_code == 0, first.output
        asked = ollama.calls

        monkeypatch.setenv("DOSSIER_OLLAMA_URL", "http://gpu-01:11434")
        second = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert second.exit_code == 0, second.output
        assert asked > 0
        assert ollama.calls == asked, "the same keys: nothing is asked a second time"

    def test_an_unset_url_with_no_default_stops_the_run_naming_the_variable(
        self, workspace: Path, monkeypatch, hf: Provider
    ):
        """Example 3: the one where `DOSSIER_HF_URL` is unset at the first cache miss.

        vLLM has no default endpoint, so there is nowhere to send the request.
        The run stops naming the variable, before any model is asked.
        """
        _synced(workspace, monkeypatch, HF)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code != 0
        assert "DOSSIER_HF_URL" in result.output
        assert hf.built == []
        assert hf.calls == 0

    def test_an_endpoint_in_pipeline_yaml_is_refused_at_load_time(
        self, workspace: Path, monkeypatch, ollama: Provider
    ):
        """Example 4: the one where someone commits `url:` in `pipeline.yaml`.

        An endpoint is per machine. Committed, it would point every other
        machine at the author's server.
        """
        path = write_pipeline(workspace, model=OLLAMA)
        path.write_text(
            path.read_text(encoding="utf-8") + "url: http://gpu-01:11434\n", encoding="utf-8"
        )

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 2
        assert "url" in result.output
        assert ollama.built == []

    def test_a_run_served_from_cache_needs_no_endpoint(
        self, workspace: Path, monkeypatch, hf: Provider
    ):
        """Counter-example (row 5): the one where every stage is served from cache.

        No model is reached, so no endpoint is needed (R0.9). Asking for one up
        front would make a fully cached run fail on a machine that could have
        completed it.
        """
        monkeypatch.setenv("DOSSIER_HF_URL", "http://gpu-01:8000/v1")
        _synced(workspace, monkeypatch, HF)
        first = _cli(workspace, monkeypatch, "run", PIPELINE)
        assert first.exit_code == 0, first.output
        asked = hf.calls

        monkeypatch.delenv("DOSSIER_HF_URL")
        second = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert second.exit_code == 0, second.output
        assert hf.calls == asked
        assert hf.built == ["http://gpu-01:8000/v1"], "the cached run built no client at all"
