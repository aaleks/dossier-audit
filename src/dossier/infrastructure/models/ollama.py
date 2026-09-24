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

import time
from collections.abc import Sequence

import httpx

from dossier.domain.model_id import check_served
from dossier.domain.ports import ImagePart
from dossier.infrastructure.models._http import (
    ModelRequestFailed,
    Sleep,
    encoded,
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
        sleep: Sleep = time.sleep,
    ) -> None:
        self.model_id = model_id
        self._name = _tag(model_id)
        self._base = url.rstrip("/")
        self._url = self._base + "/api/chat"
        self._http = http_client(api_key, transport)
        # How a refused request waits before it is sent again (R9.17).
        self._sleep = sleep
        # The digest is checked once, before the first completion -- the first
        # moment a model is reached at all (R9.4, R0.10). A client that is never
        # asked anything, as in a run served from cache, asks the server nothing.
        self._unchecked = True

    def complete(
        self,
        prompt: str,
        *,
        schema: dict | None = None,
        parts: Sequence[ImagePart] = (),
    ) -> str:
        """The model's answer to `prompt`, as the text it returned.

        `stream` false, so one request is one answer; temperature 0, so the same
        prompt asks for the same answer; `think` false, so a reasoning model
        answers instead of reasoning (R9.13). Returned verbatim for the stage to
        validate (R6.1, R6.2).
        """
        if self._unchecked:
            self._check_digest()
            self._unchecked = False

        body: dict = {
            "model": self._name,
            "messages": [_message(prompt, parts)],
            "stream": False,
            # A reasoning model under a constrained `format` can spend its whole
            # budget thinking and answer with an empty string -- 268s and nothing
            # from qwen3.5:9b on one calibration case, against 19s and a verdict
            # with this false (R9.13). Sent on every call: every completion
            # dossier asks for is structured, so no tag wants the other setting.
            # Ollama ignores the field for a model that cannot think.
            "think": False,
            "options": {"temperature": 0},
        }
        if schema is not None:
            body["format"] = schema
        response = request(self._http, "POST", self._url, json=body, sleep=self._sleep)
        return text_at(response, "message", "content")

    def _check_digest(self) -> None:
        """Stop before the first completion if the tag now holds another digest (R9.4).

        `GET <url>/api/tags` lists every model the server holds, with the digest
        each tag currently points at. A bare tag is listed with `:latest`, so
        `llama3` is looked for as `llama3:latest` too. The decision itself is
        the domain's (`check_served`).
        """
        url = self._base + "/api/tags"
        response = request(self._http, "GET", url, sleep=self._sleep)
        names = {self._name} if ":" in self._name else {self._name, f"{self._name}:latest"}
        try:
            served = {
                entry["digest"].removeprefix("sha256:")
                for entry in response.json()["models"]
                if entry.get("name") in names and isinstance(entry.get("digest"), str)
            }
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ModelRequestFailed(f"GET {url} answered with no model list") from None
        try:
            check_served(self.model_id, served=served)
        except ValueError as error:
            raise ModelRequestFailed(f"{error} (reported by {url})") from None


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
        sleep: Sleep = time.sleep,
    ) -> OllamaClient:
        return OllamaClient(
            model_id, url=url, api_key=api_key, transport=transport, sleep=sleep
        )


ollama = Ollama("http://localhost:11434")


def _message(prompt: str, parts: Sequence[ImagePart]) -> dict:
    """One user message, with its images beside it rather than inside it (R9.16).

    Ollama's own API takes images as an array on the message, not as content
    items. A client that reshaped the message into an OpenAI-style content list
    would be sending a request this server does not read -- which is the whole
    reason spec 009 has a separate client for it (R9.13).

    No `images` key at all when there are no parts, so the request is what it
    was before this rule and no cache key moves (R5.6).
    """
    message: dict = {"role": "user", "content": prompt}
    if parts:
        message["images"] = [encoded(part) for part in parts]
    return message
