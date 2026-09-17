"""R9.15 — an Anthropic provider sends each completion to `<url>/messages`, naming
the model as Anthropic does.

The requests are answered by `httpx.MockTransport`, which hands the client a
response without opening a socket: the default suite reaches no network
(R0.10), and the rule is about what is sent and what comes back, not about a
server. The reply shape is the Messages API's -- a list of content blocks --
because the answer is the first `text` block, and a model that thinks by
default puts a `thinking` block before it.
"""

from __future__ import annotations

import json

import httpx
import pytest

MODEL = "anthropic:claude-sonnet-4-5-20250929"
URL = "https://api.anthropic.com/v1"
SCHEMA = {"type": "object", "properties": {"document": {"type": "string"}}}
# Deliberately unusual whitespace: "verbatim" means the client does not parse
# and re-serialise the answer, which would hide what the model actually said.
ANSWER = '{"document":  "INC-4821",\n "fields": []}'


class Server:
    """Answers every request with one status and body, and remembers each request."""

    def __init__(
        self, status: int = 200, blocks: list[dict] | None = None, stop: str = "end_turn"
    ):
        self.status = status
        self.blocks = [{"type": "text", "text": ANSWER}] if blocks is None else blocks
        self.stop = stop
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(
                self.status, json={"type": "error", "error": {"message": "denied"}}
            )
        return httpx.Response(
            200,
            json={
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-5-20250929",
                "content": self.blocks,
                "stop_reason": self.stop,
            },
        )

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _client(server: Server, *, api_key: str | None = None):
    """The `anthropic` provider's client, built as its entry point builds it.

    Imported inside the helper: until this lands, collecting the default suite
    would error on a module that does not exist yet, and a red collection is
    not the same as a red test.
    """
    from dossier.infrastructure.models.anthropic import anthropic

    return anthropic(MODEL, url=URL, api_key=api_key, transport=server.transport)


class TestAnthropicRequests:
    """R9.15 — one request per completion, to `<url>/messages`."""

    def test_a_completion_is_one_post_naming_the_model_as_anthropic_does(self):
        """Example 1: the one where a stage's completion is one Messages call.

        The API version travels as a header, because Anthropic changes behaviour
        by that header and not by the URL. Nothing about sampling is sent:
        Anthropic's current generation refuses it, and reproducibility is the
        cache's, not the model's (R0.10, spec 005).
        """
        server = Server()

        _client(server).complete("Extract the fields.", schema=SCHEMA)

        assert len(server.requests) == 1
        request = server.requests[0]
        assert request.method == "POST"
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == "claude-sonnet-4-5-20250929"
        assert body["messages"] == [{"role": "user", "content": "Extract the fields."}]
        assert body["max_tokens"] == 16000
        assert body["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
        assert not {"temperature", "top_p", "top_k"} & body.keys()

    def test_a_key_is_sent_in_anthropics_header_and_no_key_sends_no_header(self):
        """Example 2: the one with `DOSSIER_ANTHROPIC_API_KEY` set, and the one without.

        `x-api-key`, never `Authorization: Bearer`: the header OpenAI-compatible
        servers read is one Anthropic ignores, and a key sent there would be
        both leaked and useless.
        """
        with_key, without_key = Server(), Server()

        _client(with_key, api_key="sk-ant-4f1a").complete("x", schema=SCHEMA)
        _client(without_key).complete("x", schema=SCHEMA)

        assert with_key.requests[0].headers["x-api-key"] == "sk-ant-4f1a"
        assert "authorization" not in with_key.requests[0].headers
        assert "x-api-key" not in without_key.requests[0].headers

    def test_the_answer_is_the_first_text_block_returned_verbatim(self):
        """Example 3: the one where the model thought first.

        A model that thinks by default puts a `thinking` block before its
        answer, and that block is not the answer. The text block is returned
        verbatim: validating it is the stage's job, with its one retry (R6.1,
        R6.2), and a client that reshaped it would validate something the
        model never said.
        """
        server = Server(
            blocks=[
                {"type": "thinking", "thinking": "", "signature": "…"},
                {"type": "text", "text": ANSWER},
            ]
        )

        assert _client(server).complete("x", schema=SCHEMA) == ANSWER

    def test_a_refusal_is_an_error_naming_the_model_and_the_stop_reason(self):
        """Example 4: the one where the model declined and there is no text block.

        Reported as what it is. Handed to the stage as an empty answer, R6.2
        would retry the same prompt once and then record a validation failure
        for a document the model never answered -- the wrong finding, sent to
        the wrong fix.
        """
        from dossier.infrastructure.models.anthropic import ModelRequestFailed

        server = Server(blocks=[], stop="refusal")

        with pytest.raises(ModelRequestFailed) as error:
            _client(server).complete("x", schema=SCHEMA)

        message = str(error.value)
        assert "claude-sonnet-4-5-20250929" in message
        assert "refusal" in message
