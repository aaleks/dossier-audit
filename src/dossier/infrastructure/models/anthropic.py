"""The Anthropic model client (spec 009, R9.15).

Anthropic is reached through its own Messages API, which R9.12 and R9.13 each
left to this rule. Left of the hash boundary (R0.10): what it sends is a pure
function of the stage's prompt and schema and the pinned identifier; where it
sends it is per machine and in no key (R9.2). How a request is made and how a
failure is reported is `_http`'s, shared with the other clients.

Raw httpx rather than the official SDK, as the other four providers are: one
HTTP stack, no second dependency, and the hash boundary unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from dossier.domain.ports import ImagePart
from dossier.infrastructure.models._http import (
    TIMEOUT_SECONDS,
    ModelRequestFailed,
    encoded,
    request,
)

__all__ = ["AnthropicClient", "ModelRequestFailed", "anthropic"]

# Anthropic changes behaviour by this header, not by the URL.
API_VERSION = "2023-06-01"

# Required by the API. A fixed ceiling, sized for a request that is not
# streamed: a stage's answer is structured and short, and an aggregate step's
# prose does not run to a book.
MAX_TOKENS = 16000


def _after_provider(model_id: str) -> str:
    """The model as Anthropic names it: the identifier without its prefix.

    For Anthropic that is already the dated snapshot R0.6 pins by.
    """
    return model_id.partition(":")[2]


class AnthropicClient:
    """One model, reached at one endpoint, one POST per completion."""

    def __init__(
        self,
        model_id: str,
        *,
        url: str,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model_id = model_id
        self._name = _after_provider(model_id)
        self._url = url.rstrip("/") + "/messages"
        # The key in Anthropic's own header, never as a bearer token; no header
        # at all rather than an empty one when there is no key (R9.8).
        headers = {"anthropic-version": API_VERSION}
        if api_key:
            headers["x-api-key"] = api_key
        self._http = httpx.Client(headers=headers, timeout=TIMEOUT_SECONDS, transport=transport)

    def complete(
        self,
        prompt: str,
        *,
        schema: dict | None = None,
        parts: Sequence[ImagePart] = (),
    ) -> str:
        """The model's answer to `prompt`, as the text it returned.

        Nothing about sampling is sent. Anthropic's current generation refuses
        `temperature`, `top_p` and `top_k` outright, and dossier's
        reproducibility was never the model's to provide: a model is reached
        only on a cache miss, and every answer is cached under a key naming the
        prompt, the schema and the pinned model (R0.10, spec 005).
        """
        body: dict = {
            "model": self._name,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": _content(prompt, parts)}],
        }
        if schema is not None:
            body["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        response = request(self._http, "POST", self._url, json=body)
        try:
            reply = response.json()
            blocks = reply["content"]
            stop = reply.get("stop_reason")
        except (ValueError, KeyError, TypeError):
            raise ModelRequestFailed(
                f"POST {self._url} answered with no content blocks"
            ) from None
        # A reply is a list of content blocks, and the answer is the first of
        # type `text`: a model that thinks by default puts its thinking first.
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                return block["text"]
        # No text block at all -- a `refusal`, or a reply cut off before any
        # text. Reported as what it is rather than handed to the stage as an
        # empty answer for R6.2 to retry: that would record a validation
        # failure for a document the model never answered.
        raise ModelRequestFailed(
            f"{self._name} answered with no text block (stop_reason {stop!r})"
        )


class Anthropic:
    """The `anthropic` provider: what its entry point loads.

    Called as `factory(model_id, url=..., api_key=...)` with the endpoint this
    machine reaches it at (R9.2). `default_url` is where that is when nothing
    says otherwise. `transport` is for tests, which answer requests without a
    socket.
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
    ) -> AnthropicClient:
        return AnthropicClient(model_id, url=url, api_key=api_key, transport=transport)


anthropic = Anthropic("https://api.anthropic.com/v1")


def _content(prompt: str, parts: Sequence[ImagePart]) -> str | list[dict]:
    """The message content: a plain string, or the images and then the prompt (R9.16).

    A string when there are no parts, for the reason the other clients keep one:
    the string form is what every existing cache key was computed against (R5.6).

    Images first. Anthropic documents better results when an image precedes the
    text asking about it, and the order of content blocks is the only place that
    preference can be expressed.
    """
    if not parts:
        return prompt
    return [
        *(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": part.media_type,
                    "data": encoded(part),
                },
            }
            for part in parts
        ),
        {"type": "text", "text": prompt},
    ]
