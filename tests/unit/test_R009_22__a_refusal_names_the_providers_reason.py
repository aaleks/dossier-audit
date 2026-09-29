"""R9.22 — a request a provider refuses fails naming the reason the provider
gave, and never the key.

On 2026-09-29 every judge call to Anthropic answered `400 Bad Request`, and the
cause was one sentence in a body nobody printed. Rows 1 and 2 carry the bodies
Anthropic and OpenWebUI actually answered that day.

The decision is the domain's (`refusal_reason`); then each provider's client,
answered by `httpx.MockTransport`, so the reason is shown to come through the
one path every client refuses on, key header and all. No socket is opened.
"""

from __future__ import annotations

import httpx
import pytest

from dossier.domain.refusals import refusal_reason
from dossier.infrastructure.models._http import ModelRequestFailed
from dossier.infrastructure.models.anthropic import anthropic
from dossier.infrastructure.models.ollama import ollama
from dossier.infrastructure.models.openai_compatible import openai

ANTHROPIC = "https://api.anthropic.com/v1"
OPENWEBUI = "http://localhost:8080/api"
OLLAMA = "http://localhost:11434"
DIGEST = "7f3c29a1" * 8
KEY = "sk-4f1a-do-not-print"
OPEN_SCHEMA = (
    "output_config.format.schema: For 'object' type, 'additionalProperties' "
    "must be explicitly set to false"
)
EXPIRED = "Your session has expired or the token is invalid. Please sign in again."
PROXY_PAGE = "<html>\n<head><title>502 Bad Gateway</title></head>\n<body>nginx</body>\n</html>"


class Refusing:
    """Refuses every completion with one response; lists one Ollama model when asked."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200, json={"models": [{"name": "qwen3:1.7b", "digest": DIGEST}]}
            )
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _refused(client) -> str:
    with pytest.raises(ModelRequestFailed) as error:
        client.complete("Extract the requested fields.")
    return str(error.value)


class TestWhatAReasonIs:
    """R9.22 — read where each provider writes it, on one line, and never the key."""

    @pytest.mark.parametrize(
        ("body", "reason"),
        [
            ({"type": "error", "error": {"message": OPEN_SCHEMA}}, OPEN_SCHEMA),
            ({"detail": EXPIRED}, EXPIRED),
            ({"error": "model 'qwen3:1.7b' not found"}, "model 'qwen3:1.7b' not found"),
            ({"message": "Overloaded"}, "Overloaded"),
        ],
        ids=["anthropic", "openwebui", "ollama", "message"],
    )
    def test_each_provider_is_read_where_it_writes(self, body, reason):
        """Rows 1 to 3: `error.message`, `detail`, `error` as a string, then `message`."""
        assert refusal_reason(httpx.Response(400, json=body).content) == reason

    def test_a_reason_spanning_lines_is_put_on_one(self):
        """Row 5: the one where the provider's sentence has a newline in it."""
        body = httpx.Response(400, json={"error": {"message": "schema invalid:\n  extra"}})

        assert refusal_reason(body.content) == "schema invalid: extra"

    def test_a_key_the_provider_quotes_is_removed(self):
        """Row 6: the one where the answer repeats the key it was sent."""
        body = httpx.Response(401, json={"error": {"message": f"key {KEY} is revoked"}})

        assert refusal_reason(body.content, secrets=[KEY]) == "key *** is revoked"

    @pytest.mark.parametrize(
        "content",
        [PROXY_PAGE.encode(), b'{"code": 401}', b"[]", b""],
        ids=["html", "no-reason", "a-list", "empty"],
    )
    def test_a_body_that_names_no_reason_gives_none(self, content):
        """Rows 7 and 8, counter-examples: a proxy's page, and JSON that says nothing."""
        assert refusal_reason(content) is None


class TestTheLineCarriesIt:
    """R9.22 — through each provider's client: the line `run`, `eval` and `calibrate` print."""

    def test_anthropic_says_why_it_refused(self):
        """Row 1: the one found live, a judge's schema left open."""
        server = Refusing(
            httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": OPEN_SCHEMA},
                },
            )
        )
        client = anthropic(
            "anthropic:claude-haiku-4-5-20251001",
            url=ANTHROPIC,
            api_key=KEY,
            transport=server.transport,
        )

        assert _refused(client) == (
            f"POST {ANTHROPIC}/messages answered 400 Bad Request: {OPEN_SCHEMA}"
        )

    def test_openwebui_says_why_it_refused(self):
        """Row 2: the one where the key is not one OpenWebUI knows."""
        server = Refusing(httpx.Response(401, json={"detail": EXPIRED}))
        client = openai(
            "openai:gpt-5.4-mini", url=OPENWEBUI, api_key=KEY, transport=server.transport
        )

        assert _refused(client) == (
            f"POST {OPENWEBUI}/chat/completions answered 401 Unauthorized: {EXPIRED}"
        )

    def test_ollama_says_why_it_refused(self):
        """Row 3: the one where the model is not pulled."""
        server = Refusing(httpx.Response(404, json={"error": "model 'qwen3:1.7b' not found"}))
        client = ollama(
            f"ollama:qwen3:1.7b@sha256:{DIGEST}", url=OLLAMA, transport=server.transport
        )

        assert _refused(client) == (
            f"POST {OLLAMA}/api/chat answered 404 Not Found: model 'qwen3:1.7b' not found"
        )

    def test_the_reason_comes_after_the_attempts(self):
        """Row 4: three refusals from a busy server, the reason last."""
        busy = httpx.Response(503, json={"error": {"message": "Overloaded"}})
        client = openai(
            "openai:gpt-5.4-mini",
            url=OPENWEBUI,
            api_key=KEY,
            transport=Refusing(busy).transport,
            sleep=lambda seconds: None,
        )

        assert _refused(client) == (
            f"POST {OPENWEBUI}/chat/completions answered 503 Service Unavailable "
            "(after 3 attempts): Overloaded"
        )

    @pytest.mark.parametrize(
        ("client", "header"),
        [(anthropic, "x-api-key"), (openai, "Authorization")],
        ids=["x-api-key", "bearer"],
    )
    def test_a_key_the_provider_quotes_never_reaches_the_line(self, client, header):
        """Row 6: the key removed however the provider takes it (R9.8 row 1)."""
        quoted = httpx.Response(401, json={"error": {"message": f"invalid key {KEY}"}})
        model = "anthropic:claude-haiku-4-5-20251001" if client is anthropic else "openai:x"
        refused = _refused(
            client(model, url=OPENWEBUI, api_key=KEY, transport=Refusing(quoted).transport)
        )

        assert refused.endswith(": invalid key ***"), header
        assert KEY not in refused

    def test_a_proxys_page_adds_nothing(self):
        """Row 7, a counter-example: a `502` whose body is HTML."""
        server = Refusing(httpx.Response(502, text=PROXY_PAGE))
        client = openai(
            "openai:gpt-5.4-mini",
            url=OPENWEBUI,
            api_key=KEY,
            transport=server.transport,
            sleep=lambda seconds: None,
        )

        assert _refused(client) == (
            f"POST {OPENWEBUI}/chat/completions answered 502 Bad Gateway (after 3 attempts)"
        )
