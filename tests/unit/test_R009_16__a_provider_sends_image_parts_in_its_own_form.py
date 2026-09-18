"""R9.16 — a stage may hand a model image parts, and each provider sends them in
its own native form.

Three providers, three wire formats, one caller that never learns which. The
requests are answered by `httpx.MockTransport`, so the default suite reaches no
network (R0.10) and the claim is about what was sent.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from dossier.domain.ports import ImagePart

PNG = b"\x89PNG\r\n\x1a\n fake page one"
PNG_TWO = b"\x89PNG\r\n\x1a\n fake page two"
PNG_THREE = b"\x89PNG\r\n\x1a\n fake page three"

PARTS = (
    ImagePart(media_type="image/png", data=PNG),
    ImagePart(media_type="image/png", data=PNG_TWO),
    ImagePart(media_type="image/png", data=PNG_THREE),
)
ONE_PART = PARTS[:1]

PROMPT = "Describe every chart on this page."


class Server:
    """Answers anything, and remembers what it was asked."""

    def __init__(self, body: dict):
        self.body = body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.body)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    @property
    def sent(self) -> dict:
        """The last request's body. Ollama's digest check is a GET with none."""
        posted = [r for r in self.requests if r.method == "POST"]
        return json.loads(posted[-1].content)


def openai_server() -> Server:
    return Server({"choices": [{"message": {"content": "{}"}}]})


def anthropic_server() -> Server:
    return Server(
        {
            "type": "message",
            "content": [{"type": "text", "text": "{}"}],
            "stop_reason": "end_turn",
        }
    )


DIGEST = "sha256:7f3c29a1"


class OllamaServer(Server):
    """A chat server that also answers the digest check R9.4 makes first.

    The pinned digest is verified before the first completion, so a mock that
    answered every path with a chat reply would fail here on a rule that has
    nothing to do with images.
    """

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5:7b", "digest": DIGEST}]}
            )
        return super().__call__(request)


def ollama_server() -> Server:
    return OllamaServer({"message": {"content": "{}"}, "done": True})


def openai_client(server: Server):
    from dossier.infrastructure.models.openai_compatible import openai

    return openai(
        "openai:gpt-4o-2024-08-06",
        url="https://api.openai.com/v1",
        api_key="k",
        transport=server.transport,
    )


def anthropic_client(server: Server):
    from dossier.infrastructure.models.anthropic import anthropic

    return anthropic(
        "anthropic:claude-sonnet-4-5-20250929",
        url="https://api.anthropic.com/v1",
        api_key="k",
        transport=server.transport,
    )


def ollama_client(server: Server):
    from dossier.infrastructure.models.ollama import ollama

    return ollama(
        f"ollama:qwen2.5:7b@{DIGEST}",
        url="http://localhost:11434",
        api_key=None,
        transport=server.transport,
    )


class TestEachProviderCarriesPartsItsOwnWay:
    """R9.16 — one caller, three wire formats."""

    def test_an_openai_compatible_provider_sends_a_data_uri(self):
        """Example 1: the one where a part becomes an `image_url` item."""
        server = openai_server()

        openai_client(server).complete(PROMPT, parts=ONE_PART)

        content = server.sent["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": PROMPT}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == (
            "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
        )

    def test_anthropic_sends_a_base64_source_block_before_the_prompt(self):
        """Example 2: the one where the picture comes first.

        Anthropic documents better results when an image precedes the text
        asking about it, and the order of content blocks is the only place that
        preference can be expressed.
        """
        server = anthropic_server()

        anthropic_client(server).complete(PROMPT, parts=ONE_PART)

        content = server.sent["messages"][0]["content"]
        assert content[0]["type"] == "image"
        assert content[0]["source"] == {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(PNG).decode("ascii"),
        }
        assert content[-1] == {"type": "text", "text": PROMPT}

    def test_ollama_keeps_a_string_content_and_adds_an_images_array(self):
        """Example 3: the one where the provider's own API is not OpenAI's.

        Ollama takes images beside the message rather than inside its content,
        so a client that reshaped the message into a content list would be
        sending a request its server does not read.
        """
        server = ollama_server()

        ollama_client(server).complete(PROMPT, parts=ONE_PART)

        message = server.sent["messages"][0]
        assert message["content"] == PROMPT
        assert message["images"] == [base64.b64encode(PNG).decode("ascii")]

    @pytest.mark.parametrize(
        ("build_server", "build_client", "read"),
        [
            (
                openai_server,
                openai_client,
                lambda sent: [
                    item["image_url"]["url"].split(",", 1)[1]
                    for item in sent["messages"][0]["content"]
                    if item["type"] == "image_url"
                ],
            ),
            (
                anthropic_server,
                anthropic_client,
                lambda sent: [
                    block["source"]["data"]
                    for block in sent["messages"][0]["content"]
                    if block["type"] == "image"
                ],
            ),
            (ollama_server, ollama_client, lambda sent: sent["messages"][0]["images"]),
        ],
        ids=["openai", "anthropic", "ollama"],
    )
    def test_three_parts_arrive_in_the_order_they_were_given(
        self, build_server, build_client, read
    ):
        """Example 4: the one where page order is not a set.

        A caller handing over the pages of a document in page order means it.
        A provider free to reorder them would make "the chart on page 2" a
        claim about whichever page the client happened to serialise second.
        """
        server = build_server()

        build_client(server).complete(PROMPT, parts=PARTS)

        assert read(server.sent) == [
            base64.b64encode(part.data).decode("ascii") for part in PARTS
        ]

    @pytest.mark.parametrize(
        ("build_server", "build_client"),
        [
            (openai_server, openai_client),
            (anthropic_server, anthropic_client),
            (ollama_server, ollama_client),
        ],
        ids=["openai", "anthropic", "ollama"],
    )
    def test_a_call_with_no_parts_sends_what_it_always_sent(self, build_server, build_client):
        """Counter-example (row 5): the one that must not move a single key.

        A string `content` and no `images` key. Every cache entry in every
        workspace was written against this request shape, and a client that
        started sending a one-element content list would move every stage key
        for a reason no diff explains (R5.6).
        """
        server = build_server()

        build_client(server).complete(PROMPT)

        message = server.sent["messages"][0]
        assert message["content"] == PROMPT
        assert "images" not in message
