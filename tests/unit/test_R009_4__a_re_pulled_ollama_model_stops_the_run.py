"""R9.4 — a run stops before its first model call if the server's digest for the
tag is not the pinned one.

An Ollama tag moves when the model is re-pulled, and a stage key holds the
identifier, not the weights (R5.3 row 4). If the server's `qwen2.5:7b` is no
longer the digest dossier pinned, its answers would be cached under the pinned
identifier as if the pinned weights had given them. So the digest the server
reports is checked once, before the first completion -- the first moment a
model is reached at all (R0.9).

The decision is `check_served`, a pure function. The client asks Ollama what it
holds (`GET <url>/api/tags`) and hands the answer across; `httpx.MockTransport`
answers without a socket.
"""

from __future__ import annotations

import httpx
import pytest

from dossier.domain.model_id import check_served
from dossier.infrastructure.models.ollama import ModelRequestFailed, ollama

# `_fixtures.md` writes these as 8 characters; a real digest carries 64.
PINNED_DIGEST = "7f3c29a1" * 8
REPULLED_DIGEST = "e04b6d52" * 8
PINNED = f"ollama:qwen2.5:7b@sha256:{PINNED_DIGEST}"
ANSWER = '{"document": "INC-4821", "fields": []}'


class OllamaServer:
    """An Ollama server holding `qwen2.5:7b` at one digest, counting what it is asked."""

    def __init__(self, digest: str) -> None:
        self.digest = digest
        self.listed: list[str] = []
        self.completions = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/api/tags"):
            self.listed.append(str(request.url))
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5:7b", "digest": self.digest}]}
            )
        self.completions += 1
        return httpx.Response(200, json={"message": {"role": "assistant", "content": ANSWER}})

    def client(self, url: str = "http://localhost:11434"):
        return ollama(PINNED, url=url, api_key=None, transport=httpx.MockTransport(self))


class TestARePulledOllamaModelStopsTheRun:
    """R9.4 — the digest the server holds must be the one the identifier pins."""

    def test_the_pinned_digest_lets_the_run_proceed_with_one_digest_request(self):
        """Example 1: the one where the server reports `7f3c29a1` for `qwen2.5:7b`.

        One digest request for the run, not one per call: the weights a server
        holds under a tag do not change between two requests of one run.
        """
        check_served(PINNED, served={PINNED_DIGEST})

        server = OllamaServer(digest=PINNED_DIGEST)
        client = server.client()
        client.complete("x", schema=None)
        client.complete("y", schema=None)

        assert len(server.listed) == 1
        assert server.completions == 2

    def test_a_re_pulled_model_stops_the_run_naming_both_digests_with_no_model_call(self):
        """Example 2: the one re-pulled, where the server now reports `e04b6d52`.

        Nothing is asked, so nothing can be cached under the pinned identifier.
        """
        with pytest.raises(ValueError) as decided:
            check_served(PINNED, served={REPULLED_DIGEST})
        assert PINNED_DIGEST in str(decided.value)
        assert REPULLED_DIGEST in str(decided.value)

        server = OllamaServer(digest=REPULLED_DIGEST)
        with pytest.raises(ModelRequestFailed) as stopped:
            server.client().complete("x", schema=None)

        assert PINNED_DIGEST in str(stopped.value)
        assert REPULLED_DIGEST in str(stopped.value)
        assert server.completions == 0

    def test_through_openwebuis_passthrough_it_is_checked_the_same_way(self):
        """Example 3: the one reached at `https://ai.example.internal/ollama`.

        OpenWebUI is where, not what (R9.7): the passthrough is asked for the
        same digest, and a re-pulled model behind it stops the run the same way.
        """
        server = OllamaServer(digest=REPULLED_DIGEST)

        with pytest.raises(ModelRequestFailed):
            server.client(url="https://ai.example.internal/ollama").complete("x", schema=None)

        assert server.listed == ["https://ai.example.internal/ollama/api/tags"]
        assert server.completions == 0

    def test_a_client_that_is_never_asked_anything_requests_no_digest(self):
        """Counter-example (row 4): the one where every stage is served from cache.

        A cached run never calls `complete`, and the client is built only at the
        first cache miss (R9.2 row 5). Building it asks the server nothing, so
        there is no digest request and no model call (R0.9).
        """
        server = OllamaServer(digest=REPULLED_DIGEST)

        server.client()

        assert server.listed == []
        assert server.completions == 0
