"""The OpenAI-compatible model client (spec 009, R9.12).

`openai`, `gemini` and `hf` all speak the OpenAI chat-completions API -- vLLM
serves it, and so does OpenWebUI's `/api` route -- so one client reaches all
three, and each provider's entry point is this factory with its own default
endpoint and its own way of naming a model.

Left of the hash boundary, and one of only two packages that may be (R0.9).
What it sends is a pure function of the stage's prompt and schema and the pinned
identifier; where it sends it is per machine and in no key (R9.2). Nothing here
decides whether a call happens -- the stage key does, and a cache hit never
reaches this module.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from dossier.domain.model_id import check_served

# A model can take minutes over a long document, and httpx's own default of five
# seconds would fail nearly every real request. Generous rather than unbounded,
# so a server that never answers still ends the run instead of hanging it.
TIMEOUT_SECONDS = 300.0


class ModelRequestFailed(RuntimeError):
    """A model endpoint could not be reached, or did not answer with a completion.

    The message names the URL and the status. It never carries the key: that is
    sent only in a request header, and nothing here echoes a header (R9.8 row 1).
    """


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
        checks_served: bool = False,
    ) -> None:
        self.model_id = model_id
        self._name = name
        self._base = url.rstrip("/")
        self._url = self._base + "/chat/completions"
        # Checked once, before the first completion: the model a server loaded
        # does not change between two requests of one run (R9.6).
        self._unchecked = checks_served
        # No header at all without a key, rather than an empty bearer token: a
        # local vLLM with no auth may reject `Authorization: Bearer ` as malformed.
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(headers=headers, timeout=TIMEOUT_SECONDS, transport=transport)

    def complete(self, prompt: str, *, schema: dict | None = None) -> str:
        """The model's answer to `prompt`, as the text it returned.

        Temperature 0, so the same prompt asks for the same answer. The reply is
        returned verbatim: validating it, and retrying once when it does not
        conform, is the stage's job (R6.1, R6.2), and a client that reshaped it
        would validate something the model never said.
        """
        if self._unchecked:
            self._check_served()
            self._unchecked = False

        body: dict = {
            "model": self._name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "stage_output", "schema": schema},
            }

        try:
            response = self._http.post(self._url, json=body)
        except httpx.HTTPError as error:
            raise ModelRequestFailed(f"POST {self._url} failed: {error}") from None

        if not response.is_success:
            raise ModelRequestFailed(
                f"POST {self._url} answered {response.status_code} {response.reason_phrase}"
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str):
            raise ModelRequestFailed(
                f"POST {self._url} answered {response.status_code} with no "
                "choices[0].message.content"
            )
        return content

    def _check_served(self) -> None:
        """Stop before the first completion if the server serves another model (R9.6).

        `GET <url>/models` lists what vLLM loaded: `id` is the name it serves
        under and `root` the repository it loaded, so both are offered to the
        decision. The decision itself is the domain's (`check_served`).
        """
        url = self._base + "/models"
        try:
            response = self._http.get(url)
        except httpx.HTTPError as error:
            raise ModelRequestFailed(f"GET {url} failed: {error}") from None
        if not response.is_success:
            raise ModelRequestFailed(
                f"GET {url} answered {response.status_code} {response.reason_phrase}"
            )
        try:
            listed = response.json()["data"]
            served = {
                name
                for entry in listed
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
    ) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            model_id,
            name=self._name(model_id),
            url=url,
            api_key=api_key,
            transport=transport,
            checks_served=self._checks_served,
        )


openai = OpenAICompatible("https://api.openai.com/v1")
gemini = OpenAICompatible("https://generativelanguage.googleapis.com/v1beta/openai")
# vLLM has no default: a run that needs it stops, naming DOSSIER_HF_URL (R9.2).
# It also reports which repository it loaded, which is checked before the first
# completion (R9.6). OpenAI and Gemini report no such thing for a pinned model.
hf = OpenAICompatible(None, name=_repository, checks_served=True)
