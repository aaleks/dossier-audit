"""The Ollama embedding client (spec 018, R18.3).

A vector is a model's answer, asked through this package as a completion is
(R0.16). It is reached the way the chat client reaches Ollama: the same
endpoint, the same tag with the digest removed, the same digest check before
the first request (R9.4), and `_http`'s request and error reporting. Only the
route and the body differ.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

import httpx

from dossier.infrastructure.models._http import ModelRequestFailed, Sleep, http_client, request
from dossier.infrastructure.models.ollama import _tag, check_digest

__all__ = ["ModelRequestFailed", "OllamaEmbedder", "OllamaEmbeddings", "ollama_embeddings"]


class OllamaEmbeddings:
    """One Ollama embedding model, reached at one endpoint, one POST per `embed`."""

    def __init__(
        self,
        model_id: str,
        *,
        url: str,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Sleep = time.sleep,
    ) -> None:
        self.model_id = model_id
        self._name = _tag(model_id)
        self._base = url.rstrip("/")
        self._url = self._base + "/api/embed"
        self._http = http_client(api_key, transport)
        self._sleep = sleep
        # Checked once, before the first request, as the chat client checks it:
        # an embed served wholly from the cache asks the server nothing (R18.3).
        self._unchecked = True
        self.last_tokens: int | None = None
        self._checking = threading.Lock()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in the order the texts were given.

        Every text goes in one request. `truncate` is false: Ollama would
        otherwise cut a text longer than the model's context without saying so,
        and the vector would describe part of the chunk it is filed under. A
        text too long is refused, with Ollama's reason, instead.

        No texts, no request: there is nothing to ask.
        """
        if not texts:
            return []
        if self._unchecked:
            with self._checking:
                if self._unchecked:
                    check_digest(self._http, self._base, self.model_id, sleep=self._sleep)
                    self._unchecked = False
        body = {"model": self._name, "input": list(texts), "truncate": False}
        response = request(self._http, "POST", self._url, json=body, sleep=self._sleep)
        vectors = _vectors(response)
        # What the model counted, for the trace of this request (R11.33).
        counted = response.json().get("prompt_eval_count")
        self.last_tokens = counted if isinstance(counted, int) else None
        if len(vectors) != len(texts):
            # A vector filed under the wrong chunk would be found for text it
            # does not describe, so a count that does not match files nothing.
            raise ModelRequestFailed(
                f"POST {self._url} answered {len(vectors)} embeddings for "
                f"{len(texts)} texts; each text needs exactly one"
            )
        return vectors


def _vectors(response: httpx.Response) -> list[list[float]]:
    """`embeddings` from an answer, each a list of floats, or `ModelRequestFailed`."""
    try:
        answered = response.json()["embeddings"]
        if not isinstance(answered, list):
            raise TypeError
        return [[_number(value) for value in vector] for vector in answered]
    except (ValueError, KeyError, TypeError):
        raise ModelRequestFailed(
            f"{response.request.method} {response.request.url} answered "
            f"{response.status_code} with no embeddings"
        ) from None


def _number(value: object) -> float:
    # `bool` is an `int` in Python, and `true` is not a coordinate.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError
    return float(value)


class OllamaEmbedder:
    """The `ollama` embedding provider: what its `dossier.embeddings` entry point loads.

    Called as `factory(model_id, url=..., api_key=...)`, as a chat provider is,
    with the endpoint this machine reaches Ollama at (R9.2). `transport` is for
    tests, which answer requests without a socket.
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
        sleep: Sleep = time.sleep,
    ) -> OllamaEmbeddings:
        return OllamaEmbeddings(
            model_id, url=url, api_key=api_key, transport=transport, sleep=sleep
        )


# The chat provider's default, so one `DOSSIER_OLLAMA_URL` serves both.
ollama_embeddings = OllamaEmbedder("http://localhost:11434")
