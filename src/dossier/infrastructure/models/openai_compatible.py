"""The OpenAI-compatible model client (spec 009, R9.12).

`openai`, `gemini` and `hf` all speak the OpenAI chat-completions API -- vLLM
serves it, and so does OpenWebUI's `/api` route -- so one client reaches all
three, and each provider's entry point is this factory with its own default
endpoint and its own way of naming a model.

Left of the hash boundary, one of the three packages that may be (R0.10).
What it sends is a pure function of the stage's prompt and schema and the pinned
identifier; where it sends it is per machine and in no key (R9.2). Nothing here
decides whether a call happens -- the stage key does, and a cache hit never
reaches this module. How a request is made and how a failure is reported is
`_http`'s, shared with the Ollama client.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence

import httpx

from dossier.domain.model_id import check_served
from dossier.domain.ports import ImagePart, Reply
from dossier.infrastructure.models._http import (
    TIMEOUT_SECONDS,
    ModelRequestFailed,
    Sleep,
    count_at,
    encoded,
    http_client,
    request,
    text_at,
)

__all__ = [
    "TIMEOUT_SECONDS",
    "ModelRequestFailed",
    "OpenAICompatible",
    "OpenAICompatibleClient",
    "gemini",
    "hf",
    "openai",
]


def _after_provider(model_id: str) -> str:
    """The model as OpenAI and Gemini name it: the identifier without its prefix."""
    return model_id.partition(":")[2]


def _repository(model_id: str) -> str:
    """The model as vLLM names it: its repository, without dossier's `@revision`.

    The revision is how dossier pins the weights (R9.5). vLLM serves a model
    under its repository name and knows nothing of the pin.
    """
    return _after_provider(model_id).partition("@")[0]


class OpenAICompatibleClient:
    """One model, reached at one endpoint, one POST per completion."""

    def __init__(
        self,
        model_id: str,
        *,
        name: str,
        url: str,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Sleep = time.sleep,
        checks_served: bool = False,
    ) -> None:
        self.model_id = model_id
        self._name = name
        self._base = url.rstrip("/")
        self._url = self._base + "/chat/completions"
        self._http = http_client(api_key, transport)
        # How a refused request waits before it is sent again (R9.17).
        self._sleep = sleep
        # Checked once, before the first completion: the model a server loaded
        # does not change between two requests of one run (R9.6). Once however
        # many workers ask at once (R9.19): the rest wait for it.
        self._unchecked = checks_served
        self._checking = threading.Lock()

    def complete(
        self,
        prompt: str,
        *,
        schema: dict | None = None,
        parts: Sequence[ImagePart] = (),
    ) -> str:
        """The model's answer to `prompt`, as the text it returned.

        Temperature 0, so the same prompt asks for the same answer. The reply is
        returned verbatim for the stage to validate, and to retry once when it
        does not conform (R6.1, R6.2).
        """
        if self._unchecked:
            with self._checking:
                if self._unchecked:
                    self._check_served()
                    self._unchecked = False

        body: dict = {
            "model": self._name,
            "messages": [{"role": "user", "content": _content(prompt, parts)}],
            "temperature": 0,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "stage_output", "schema": schema},
            }
        response = request(self._http, "POST", self._url, json=body, sleep=self._sleep)
        # What the answer cost, where the chat-completions API says it (R9.18).
        return Reply(
            text_at(response, "choices", 0, "message", "content"),
            input_tokens=count_at(response, "usage", "prompt_tokens"),
            output_tokens=count_at(response, "usage", "completion_tokens"),
        )

    def _check_served(self) -> None:
        """Stop before the first completion if the server serves another model (R9.6).

        `GET <url>/models` lists what vLLM loaded: `id` is the name it serves
        under and `root` the repository it loaded, so both are offered to the
        decision. The decision itself is the domain's (`check_served`).
        """
        url = self._base + "/models"
        response = request(self._http, "GET", url, sleep=self._sleep)
        try:
            served = {
                name
                for entry in response.json()["data"]
                for name in (entry.get("id"), entry.get("root"))
                if isinstance(name, str)
            }
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ModelRequestFailed(f"GET {url} answered with no model list") from None
        try:
            check_served(self.model_id, served=served)
        except ValueError as error:
            raise ModelRequestFailed(f"{error} (reported by {url})") from None


class OpenAICompatible:
    """A provider reached through the chat-completions API: what its entry point loads.

    Called as `factory(model_id, url=..., api_key=...)` with the endpoint this
    machine reaches it at (R9.2). `default_url` is where that is when nothing
    says otherwise. `transport` is for tests, which answer requests without a
    socket.
    """

    def __init__(
        self,
        default_url: str | None,
        *,
        name: Callable[[str], str] = _after_provider,
        checks_served: bool = False,
    ) -> None:
        self.default_url = default_url
        self._name = name
        self._checks_served = checks_served

    def __call__(
        self,
        model_id: str,
        *,
        url: str,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Sleep = time.sleep,
    ) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            model_id,
            name=self._name(model_id),
            url=url,
            api_key=api_key,
            transport=transport,
            checks_served=self._checks_served,
            sleep=sleep,
        )


openai = OpenAICompatible("https://api.openai.com/v1")
gemini = OpenAICompatible("https://generativelanguage.googleapis.com/v1beta/openai")
# vLLM has no default: a run that needs it stops, naming DOSSIER_HF_URL (R9.2).
# It also reports which repository it loaded, which is checked before the first
# completion (R9.6). OpenAI and Gemini report no such thing for a pinned model.
hf = OpenAICompatible(None, name=_repository, checks_served=True)


def _content(prompt: str, parts: Sequence[ImagePart]) -> str | list[dict]:
    """The message content: a plain string, or the prompt and its images (R9.16).

    A string when there are no parts. Not a one-element content list -- every
    cache entry in every workspace was written against the string form, and
    changing it would move every stage key for a reason no diff explains (R5.6).

    The prompt comes first here. OpenAI's own guidance puts the instruction
    before the images it is about, which is the opposite of Anthropic's, and
    each client follows its own provider rather than a shape dossier invented.
    """
    if not parts:
        return prompt
    return [
        {"type": "text", "text": prompt},
        *(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{part.media_type};base64,{encoded(part)}"},
            }
            for part in parts
        ),
    ]
