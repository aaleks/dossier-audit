"""R18.3 -- the request an embedding is asked with, through Ollama's `/api/embed`.

R18.3's rows are about when a chunk is embedded, and are proved by
`test_R018_3__a_chunk_is_embedded_only_on_a_cache_miss.py` against a fake
provider. This file proves the other half: what the real provider sends and
what it accepts back, so the fake there is a claim about a request this client
actually makes. `httpx.MockTransport` answers without opening a socket.
"""

from __future__ import annotations

import json

import httpx
import pytest

from dossier.infrastructure.models.ollama_embed import (
    ModelRequestFailed,
    OllamaEmbedder,
    OllamaEmbeddings,
    ollama_embeddings,
)
from dossier.infrastructure.models.registry import UnknownProvider, embedding_provider

# The registry's digest for `qwen3-embedding:4b-fp16` on 2026-10-01 (spec 018).
DIGEST = "3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
REPULLED = "e04b6d52" * 8
PINNED = f"ollama:qwen3-embedding:4b-fp16@sha256:{DIGEST}"
URL = "http://localhost:11434"
# A chunk's text as R18.3 embeds it: its heading path, then its text.
IMPACT = "INC-4821 — Card payments declined at checkout\nImpact\nCHF 48'200 declined."
COMMENTS = "INC-4821 — Card payments declined at checkout\nComments\nRolled back at 14:40."
TOO_LONG = "the input length exceeds the context length"


class Server:
    """An Ollama server holding the embedding model at one digest.

    Answers each text with a vector naming its position, so an answer out of
    order is visible. `answer` overrides what `/api/embed` returns.
    """

    def __init__(
        self, *, digest: str = DIGEST, status: int = 200, answer: dict | None = None
    ) -> None:
        self.digest = digest
        self.status = status
        self.answer = answer
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/api/tags"):
            return httpx.Response(
                200,
                json={"models": [{"name": "qwen3-embedding:4b-fp16", "digest": self.digest}]},
            )
        if self.status != 200:
            return httpx.Response(self.status, json={"error": TOO_LONG})
        if self.answer is not None:
            return httpx.Response(200, json=self.answer)
        texts = json.loads(request.content)["input"]
        return httpx.Response(
            200,
            json={
                "model": "qwen3-embedding:4b-fp16",
                "embeddings": [[float(i), 1.0, 0.0] for i, _ in enumerate(texts)],
                "total_duration": 1,
                "load_duration": 1,
                "prompt_eval_count": 12,
            },
        )

    @property
    def posted(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "POST"]

    @property
    def listed(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "GET"]

    def client(self, url: str = URL) -> OllamaEmbeddings:
        return ollama_embeddings(
            PINNED, url=url, api_key=None, transport=httpx.MockTransport(self)
        )


class TestOllamaEmbeddingsRequest:
    """One POST to `<url>/api/embed` per `embed`, naming the tag, refusing to truncate."""

    def test_one_post_names_the_tag_and_refuses_to_truncate(self):
        """No row — the body is exactly the model's tag, the texts, and `truncate: false`.

        The digest is not sent: Ollama does not accept `@sha256:` in a name, and
        it is checked separately (R9.4). `truncate` false, because a text cut
        silently would be filed under a vector describing part of it.
        """
        server = Server()

        server.client(url="http://localhost:8080/ollama/").embed([IMPACT, COMMENTS])

        assert len(server.posted) == 1
        request = server.posted[0]
        assert str(request.url) == "http://localhost:8080/ollama/api/embed"
        assert json.loads(request.content) == {
            "model": "qwen3-embedding:4b-fp16",
            "input": [IMPACT, COMMENTS],
            "truncate": False,
        }

    def test_two_texts_give_two_vectors_in_their_order(self):
        """No row — the vectors come back one per text, in the order the texts were given."""
        server = Server()

        vectors = server.client().embed([IMPACT, COMMENTS])

        assert vectors == [[0.0, 1.0, 0.0], [1.0, 1.0, 0.0]]

    def test_a_count_that_does_not_match_the_texts_is_refused(self):
        """No row — one vector for two texts is refused, naming both counts.

        A vector filed under the wrong chunk would be found for text it does
        not describe, so nothing is returned to file.
        """
        server = Server(answer={"embeddings": [[0.0, 1.0, 0.0]]})

        with pytest.raises(ModelRequestFailed) as refused:
            server.client().embed([IMPACT, COMMENTS])

        message = str(refused.value)
        assert "1 embeddings for 2 texts" in message
        assert "http://localhost:11434/api/embed" in message

    def test_an_answer_with_no_embeddings_is_refused(self):
        """No row — an answer with no `embeddings` list is refused, not read as no vectors."""
        server = Server(answer={"model": "qwen3-embedding:4b-fp16"})

        with pytest.raises(ModelRequestFailed, match="with no embeddings"):
            server.client().embed([IMPACT])

    def test_a_400_surfaces_with_ollamas_reason(self):
        """No row — a text longer than the model's context is refused with Ollama's words.

        `400` alone says a request was refused, not why; the why is the one
        sentence Ollama wrote (R9.22). A `400` is not retried (R9.17).
        """
        server = Server(status=400)

        with pytest.raises(ModelRequestFailed) as refused:
            server.client().embed([IMPACT])

        message = str(refused.value)
        assert "400" in message
        assert TOO_LONG in message
        assert len(server.posted) == 1

    def test_the_pinned_digest_is_checked_once_before_the_first_embed(self):
        """No row — the served digest is checked as R9.4 checks a chat model's: once."""
        server = Server()
        client = server.client()

        client.embed([IMPACT])
        client.embed([COMMENTS])

        assert [str(request.url) for request in server.listed] == [URL + "/api/tags"]
        assert len(server.posted) == 2

    def test_a_re_pulled_model_is_refused_before_any_text_is_embedded(self):
        """No row — the tag now holding another digest stops the embed, naming both (R9.4).

        A vector from other weights would be cached under the pinned identifier
        and never compared with the right ones again.
        """
        server = Server(digest=REPULLED)

        with pytest.raises(ModelRequestFailed) as refused:
            server.client().embed([IMPACT])

        assert DIGEST in str(refused.value)
        assert REPULLED in str(refused.value)
        assert server.posted == []

    def test_no_texts_ask_nothing(self):
        """No row — an embed of no texts sends no request and checks no digest."""
        server = Server(digest=REPULLED)

        assert server.client().embed([]) == []
        assert server.requests == []

    def test_the_ollama_embedding_provider_is_installed_and_gemini_is_not(self):
        """No row — the provider is found by entry point, as a chat provider is (R9.1).

        One endpoint serves both: the default is the chat provider's, so
        `DOSSIER_OLLAMA_URL` reaches the embedding model too (R9.2).
        """
        factory = embedding_provider("ollama")

        assert isinstance(factory, OllamaEmbedder)
        assert factory.default_url == "http://localhost:11434"
        with pytest.raises(UnknownProvider, match="embedding provider 'gemini'.*ollama"):
            embedding_provider("gemini")
