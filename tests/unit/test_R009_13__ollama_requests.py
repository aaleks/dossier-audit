"""R9.13 — an Ollama provider sends each completion to `<url>/api/chat`, naming
the model by its tag.

Ollama is reached through its native API, which is also what OpenWebUI's
`/ollama` passthrough speaks. The requests are answered by `httpx.MockTransport`,
which hands the client a response without opening a socket (R0.9).
"""

from __future__ import annotations

import json

import httpx
import pytest

from dossier.infrastructure.models.ollama import ModelRequestFailed, Ollama, ollama
from dossier.infrastructure.models.registry import provider

DIGEST = "7f3c29a1" * 8
# `_fixtures.md` writes the digest as `7f3c29a1`; a real one carries 64 characters.
PINNED = f"ollama:qwen2.5:7b@sha256:{DIGEST}"
PASSTHROUGH = "http://localhost:8080/ollama"
SCHEMA = {"type": "object", "properties": {"document": {"type": "string"}}}
# Unusual whitespace on purpose: "verbatim" means not parsed and re-serialised.
ANSWER = '{"document":  "INC-4821",\n "fields": []}'


class Server:
    """An Ollama server: answers chat with one status, and lists the pinned tag."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/api/tags"):
            # What Ollama lists, for the digest check before a first completion (R9.4).
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5:7b", "digest": DIGEST}]}
            )
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "unauthorized"})
        return httpx.Response(
            200,
            json={"model": "qwen2.5:7b", "message": {"role": "assistant", "content": ANSWER}},
        )

    @property
    def posted(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "POST"]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


class TestOllamaRequests:
    """R9.13 — one POST per completion, to `<url>/api/chat`, naming the tag."""

    def test_a_completion_is_one_post_naming_the_model_by_its_tag(self):
        """Example 1: the one reached through OpenWebUI's `/ollama` passthrough."""
        server = Server()
        client = ollama(PINNED, url=PASSTHROUGH, api_key=None, transport=server.transport)

        client.complete("Extract the fields.", schema=SCHEMA)

        assert len(server.posted) == 1
        request = server.posted[0]
        assert str(request.url) == "http://localhost:8080/ollama/api/chat"
        body = json.loads(request.content)
        assert body["model"] == "qwen2.5:7b"
        assert body["stream"] is False
        # Not a detail: a reasoning model left to think under a constrained
        # `format` can spend its budget and answer with an empty string, which
        # is a call that cost minutes and returned nothing (R9.13).
        assert body["think"] is False
        assert body["options"]["temperature"] == 0
        assert body["format"] == SCHEMA

    def test_a_key_is_sent_as_a_bearer_token_and_no_key_sends_no_header(self):
        """Example 2: the one with `DOSSIER_OLLAMA_API_KEY` set, and the one without."""
        with_key, without_key = Server(), Server()

        keyed = ollama(PINNED, url=PASSTHROUGH, api_key="sk-4f1a", transport=with_key.transport)
        keyless = ollama(PINNED, url=PASSTHROUGH, api_key=None, transport=without_key.transport)
        keyed.complete("x", schema=SCHEMA)
        keyless.complete("x", schema=SCHEMA)

        assert with_key.posted[0].headers["authorization"] == "Bearer sk-4f1a"
        assert "authorization" not in without_key.posted[0].headers

    def test_the_answer_is_returned_verbatim(self):
        """Example 3: the one where the server answers 200.

        Validating the answer is the stage's job (R6.1, R6.2). A client that
        reshaped it would validate something the model never said.
        """
        server = Server()
        client = ollama(PINNED, url=PASSTHROUGH, api_key=None, transport=server.transport)

        assert client.complete("x", schema=SCHEMA) == ANSWER

    def test_a_refusal_names_the_url_and_the_status_and_never_the_key(self):
        """Example 4: the one where OpenWebUI answers 401."""
        server = Server(status=401)
        client = ollama(PINNED, url=PASSTHROUGH, api_key="sk-4f1a", transport=server.transport)

        with pytest.raises(ModelRequestFailed) as error:
            client.complete("x", schema=SCHEMA)

        message = str(error.value)
        assert "http://localhost:8080/ollama/api/chat" in message
        assert "401" in message
        assert "sk-4f1a" not in message

    def test_a_gemini_model_is_not_reached_this_way(self):
        """Counter-example (row 5): the one R9.12 reaches.

        The installed `ollama` provider is this client and `gemini` is not, so
        each model goes to the API its server speaks.
        """
        assert isinstance(provider("ollama"), Ollama)
        assert not isinstance(provider("gemini"), Ollama)
