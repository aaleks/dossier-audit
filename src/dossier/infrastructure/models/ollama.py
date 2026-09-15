"""The Ollama model client (spec 009, R9.13).

Ollama is reached through its native API, which is also what OpenWebUI's
`/ollama` passthrough speaks -- so the same client reaches Ollama on a laptop,
on a GPU server, or behind OpenWebUI, and only the endpoint differs (R9.2, R9.7).

The model is named by its tag. dossier pins it by digest (R9.3), and Ollama does
not accept `@sha256:...` as part of a name, so the digest is removed from what
is sent and checked separately (R9.4). How a request is made and how a failure
is reported is `_http`'s, shared with the OpenAI-compatible client.
"""

from __future__ import annotations

import httpx

from dossier.infrastructure.models._http import (
    ModelRequestFailed,
    http_client,
    request,
    text_at,
)

__all__ = ["ModelRequestFailed", "Ollama", "OllamaClient", "ollama"]


def _tag(model_id: str) -> str:
    """`qwen2.5:7b` from `ollama:qwen2.5:7b@sha256:...`: the name Ollama serves it under."""
    return model_id.partition(":")[2].partition("@")[0]


class OllamaClient:
    """One Ollama model, reached at one endpoint, one POST per completion."""

    def __init__(
        self,
        model_id: str,
        *,
        url: str,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model_id = model_id
        self._name = _tag(model_id)
        self._url = url.rstrip("/") + "/api/chat"
        self._http = http_client(api_key, transport)

    def complete(self, prompt: str, *, schema: dict | None = None) -> str:
        """The model's answer to `prompt`, as the text it returned.

        `stream` false, so one request is one answer; temperature 0, so the same
        prompt asks for the same answer. Returned verbatim for the stage to
        validate (R6.1, R6.2).
        """
        body: dict = {
            "model": self._name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0},
        }
        if schema is not None:
            body["format"] = schema
        response = request(self._http, "POST", self._url, json=body)
        return text_at(response, "message", "content")


class Ollama:
    """The `ollama` provider: what its entry point loads.

    Called as `factory(model_id, url=..., api_key=...)` with the endpoint this
    machine reaches it at (R9.2). `transport` is for tests, which answer
    requests without a socket.
    """

    def __init__(self, default_url: str | None) -> None:
        self.default_url = default_url

    def __call__(
        self,
        model_id: str,
        *,
        url: str,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> OllamaClient:
        return OllamaClient(model_id, url=url, api_key=api_key, transport=transport)


ollama = Ollama("http://localhost:11434")
