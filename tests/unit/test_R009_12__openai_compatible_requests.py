"""R9.12 — an OpenAI-compatible provider sends each completion to
`<url>/chat/completions`, naming the model as its provider does.

`openai`, `gemini` and `hf` all speak the OpenAI chat-completions API, so one
client reaches all three. The requests are answered by `httpx.MockTransport`,
which hands the client a response without opening a socket: the default suite
reaches no network (R0.9), and the rule is about what is sent and what comes
back, not about a server.
"""

from __future__ import annotations

import json

import httpx
import pytest

from dossier.infrastructure.models.openai_compatible import (
    ModelRequestFailed,
    OpenAICompatible,
    gemini,
    hf,
)
from dossier.infrastructure.models.registry import provider

GEMINI = "gemini:gemini-3.5-flash-lite"
OPENWEBUI = "http://localhost:8080/api"
SCHEMA = {"type": "object", "properties": {"document": {"type": "string"}}}
# Deliberately unusual whitespace: "verbatim" means the client does not parse
# and re-serialise the answer, which would hide what the model actually said.
ANSWER = '{"document":  "INC-4821",\n "fields": []}'


class Server:
    """Answers every request with one status and body, and remembers each request."""

    def __init__(self, status: int = 200, content: str = ANSWER) -> None:
        self.status = status
        self.content = content
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/models"):
            # What vLLM lists before an `hf` client's first completion (R9.6).
            return httpx.Response(200, json={"data": [{"id": "Qwen/Qwen2.5-7B-Instruct"}]})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "denied"}})
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": self.content}}]}
        )

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


class TestOpenAICompatibleRequests:
    """R9.12 — one request per completion, to `<url>/chat/completions`."""

    def test_a_completion_is_one_post_naming_the_model_as_gemini_does(self):
        """Example 1: the one reached through OpenWebUI at `http://localhost:8080/api`."""
        server = Server()
        client = gemini(GEMINI, url=OPENWEBUI, api_key=None, transport=server.transport)

        client.complete("Extract the fields.", schema=SCHEMA)

        assert len(server.requests) == 1
        request = server.requests[0]
        assert request.method == "POST"
        assert str(request.url) == "http://localhost:8080/api/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "gemini-3.5-flash-lite"
        assert body["temperature"] == 0
        assert body["response_format"]["json_schema"]["schema"] == SCHEMA

    def test_a_key_is_sent_as_a_bearer_token_and_no_key_sends_no_header(self):
        """Example 2: the one with `DOSSIER_GEMINI_API_KEY` set, and the one without."""
        with_key, without_key = Server(), Server()

        gemini(GEMINI, url=OPENWEBUI, api_key="sk-4f1a", transport=with_key.transport).complete(
            "x", schema=SCHEMA
        )
        gemini(GEMINI, url=OPENWEBUI, api_key=None, transport=without_key.transport).complete(
            "x", schema=SCHEMA
        )

        assert with_key.requests[0].headers["authorization"] == "Bearer sk-4f1a"
        assert "authorization" not in without_key.requests[0].headers

    def test_the_answer_is_returned_verbatim(self):
        """Example 3: the one where the server answers 200.

        Validating the answer is the stage's job, with its one retry (R6.1,
        R6.2). A client that reshaped it would validate something the model
        never said.
        """
        server = Server()
        client = gemini(GEMINI, url=OPENWEBUI, api_key=None, transport=server.transport)

        assert client.complete("x", schema=SCHEMA) == ANSWER

    def test_a_refusal_names_the_url_and_the_status_and_never_the_key(self):
        """Example 4: the one where OpenWebUI answers 401."""
        server = Server(status=401)
        client = gemini(GEMINI, url=OPENWEBUI, api_key="sk-4f1a", transport=server.transport)

        with pytest.raises(ModelRequestFailed) as error:
            client.complete("x", schema=SCHEMA)

        message = str(error.value)
        assert "http://localhost:8080/api/chat/completions" in message
        assert "401" in message
        assert "sk-4f1a" not in message

    def test_an_anthropic_model_is_not_reached_this_way(self):
        """Counter-example (row 5): the one with its own API.

        The installed `anthropic` provider is not this client, so an Anthropic
        model is never sent to a chat-completions route it does not serve.
        """
        assert not isinstance(provider("anthropic"), OpenAICompatible)
        assert isinstance(provider("gemini"), OpenAICompatible)

    def test_vllm_is_asked_for_the_repository_without_dossiers_revision(self):
        """The rule's own sentence: `hf` names the model as vLLM serves it.

        `@1c0f8e6b...` is how dossier pins the revision (R9.5), not a name vLLM
        knows; it serves the model under its repository.
        """
        server = Server()
        client = hf(
            "hf:Qwen/Qwen2.5-7B-Instruct@" + "1c0f8e6b" * 5,
            url="http://gpu-01:8000/v1",
            api_key=None,
            transport=server.transport,
        )

        client.complete("x", schema=SCHEMA)

        posted = [request for request in server.requests if request.method == "POST"]
        assert json.loads(posted[0].content)["model"] == "Qwen/Qwen2.5-7B-Instruct"
