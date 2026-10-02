"""R9.24 — a reply that stopped at the model's output limit is no answer: its
request fails as sent, and nothing is cached.

No provider was asked why a reply stopped, and a step with no schema took a
reply cut off for length as its answer and cached it. Each provider says it:
`finish_reason`, `done_reason` or `stop_reason`. Here each client is answered by
`httpx.MockTransport`, without a socket, and the stage is shown what it does with
the refusal.
"""

from __future__ import annotations

import httpx
import pytest

from dossier.application.extract import run_stage
from dossier.domain.refusals import UnanswerableRequest
from dossier.infrastructure.models._http import ReplyCutOff
from dossier.infrastructure.models.anthropic import anthropic
from dossier.infrastructure.models.ollama import ollama
from dossier.infrastructure.models.openai_compatible import gemini

GEMINI = "gemini:gemini-3.5-flash-lite"
DIGEST = "7f3c29a1" * 8
OLLAMA = f"ollama:qwen2.5:7b@sha256:{DIGEST}"
CLAUDE = "anthropic:claude-sonnet-4-5-20250929"
PARTIAL = '{"document": "INC-4821", "fields": [{"field": "loss_amo'


def _openai(stopped: str) -> httpx.Response:
    message = {"role": "assistant", "content": PARTIAL}
    return httpx.Response(
        200, json={"choices": [{"message": message, "finish_reason": stopped}]}
    )


def _ollama(stopped: str):
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            # The digest check before the first completion (R9.4).
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5:7b", "digest": f"sha256:{DIGEST}"}]}
            )
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": PARTIAL},
                "done": True,
                "done_reason": stopped,
            },
        )

    return answer


def _anthropic(stopped: str) -> httpx.Response:
    return httpx.Response(
        200, json={"content": [{"type": "text", "text": PARTIAL}], "stop_reason": stopped}
    )


def _clients(stopped: dict[str, str]):
    """The three clients, each answered with `PARTIAL` and its own reason for stopping."""
    return {
        "finish_reason": gemini(
            GEMINI,
            url="http://localhost:8080/api",
            api_key=None,
            transport=httpx.MockTransport(lambda request: _openai(stopped["finish_reason"])),
        ),
        "done_reason": ollama(
            OLLAMA,
            url="http://localhost:11434",
            api_key=None,
            transport=httpx.MockTransport(_ollama(stopped["done_reason"])),
        ),
        "stop_reason": anthropic(
            CLAUDE,
            url="https://api.anthropic.com/v1",
            api_key="sk-4f1a",
            transport=httpx.MockTransport(lambda request: _anthropic(stopped["stop_reason"])),
        ),
    }


CUT_OFF = {"finish_reason": "length", "done_reason": "length", "stop_reason": "max_tokens"}


class TestAReplyCutOffAtItsLimitIsNoAnswer:
    """R9.24 — each provider's word for it, and the stage's failure."""

    @pytest.mark.parametrize("said", sorted(CUT_OFF))
    def test_a_reply_cut_off_is_refused_as_sent(self, said: str):
        """Rows 1 to 3 — the ones cut off, in OpenAI's, Ollama's and Anthropic's words."""
        client = _clients(CUT_OFF)[said]

        with pytest.raises(ReplyCutOff) as refused:
            client.complete("Extract INC-4821.")

        assert isinstance(refused.value, UnanswerableRequest)
        limit = f'its output limit ({said} "{CUT_OFF[said]}")'
        assert str(refused.value) == f"{client.model_id} cut its reply off at {limit}"

    def test_a_cut_off_report_fails_its_unit_and_is_not_an_answer(self):
        """Row 4 — the one an `aggregate` step with no schema was cut off on."""
        client = _clients(CUT_OFF)["finish_reason"]

        result = run_stage(
            document="incidents",
            prompt="Summarise the four incidents.",
            schema=None,
            model=client,
            input_documents={},
        )

        assert result.failed and result.text is None
        assert result.error == (
            f'{GEMINI} cut its reply off at its output limit (finish_reason "length")'
        )

    @pytest.mark.parametrize("said", sorted(CUT_OFF))
    def test_a_reply_that_finished_is_the_answer(self, said: str):
        """Row 5, counter-example — the ones that stopped because they were done."""
        finished = {"finish_reason": "stop", "done_reason": "stop", "stop_reason": "end_turn"}

        assert _clients(finished)[said].complete("Extract INC-4821.") == PARTIAL
