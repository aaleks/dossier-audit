"""R9.18 — a reply carries the tokens its provider counted, and a count the
provider did not give is absent, never zero.

Each provider says what an answer cost in its own words, on every answer. The
client reads them where that provider puts them and hands them back on the
reply, which is still the text it always was. Nothing here opens a socket: each
server is a transport answering one scripted body.
"""

from __future__ import annotations

import httpx
import pytest

from dossier.domain.ports import Reply
from dossier.domain.usage import Tokens, tokens_of

ANSWER = '{"document": "INC-4821", "fields": []}'


def _serving(body: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=body))


def _gemini(body: dict):
    from dossier.infrastructure.models.openai_compatible import gemini

    return gemini(
        "gemini:gemini-3.5-flash-lite",
        url="http://localhost:8080/api",
        transport=_serving(body),
    )


class TestAReplyCarriesTheTokensItsProviderCounted:
    """R9.18 — a reply carries the tokens its provider counted, and a count the
    provider did not give is absent, never zero."""

    def test_an_openai_compatible_answer_says_what_it_cost(self):
        """Row 1: the one where OpenWebUI's `usage` names prompt and completion tokens."""
        body = {
            "choices": [{"message": {"content": ANSWER}}],
            "usage": {"prompt_tokens": 1204, "completion_tokens": 212},
        }

        reply = _gemini(body).complete("Extract the fields.")

        assert reply == ANSWER
        assert tokens_of(reply) == Tokens(input=1204, output=212)

    def test_an_anthropic_answer_says_it_in_anthropics_words(self):
        """Row 2: the one where the counts are `input_tokens` and `output_tokens`."""
        from dossier.infrastructure.models.anthropic import anthropic

        body = {
            "content": [{"type": "text", "text": ANSWER}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1204, "output_tokens": 212},
        }
        client = anthropic(
            "anthropic:claude-sonnet-4-5-20250929",
            url="https://api.anthropic.com/v1",
            transport=_serving(body),
        )

        reply = client.complete("Extract the fields.")

        assert reply == ANSWER
        assert tokens_of(reply) == Tokens(input=1204, output=212)

    def test_an_ollama_answer_says_it_in_ollamas_words(self):
        """Row 3: the one where the counts are `prompt_eval_count` and `eval_count`."""
        from dossier.infrastructure.models.ollama import ollama

        body = {
            "message": {"role": "assistant", "content": ANSWER},
            "prompt_eval_count": 1204,
            "eval_count": 212,
        }
        client = ollama(
            "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8,
            url="http://localhost:11434",
            transport=_serving(body),
        )
        client._unchecked = False  # the digest check is R9.4's, not this rule's

        reply = client.complete("Extract the fields.")

        assert reply == ANSWER
        assert tokens_of(reply) == Tokens(input=1204, output=212)

    def test_an_answer_with_no_usage_reported_nothing(self):
        """Row 4, a counter-example: the one where OpenWebUI passed on no `usage`.

        Not 0. A passthrough that strips the count has not reported a free
        completion.
        """
        reply = _gemini({"choices": [{"message": {"content": ANSWER}}]}).complete("Extract.")

        assert reply == ANSWER
        assert tokens_of(reply) == Tokens(input=None, output=None)

    @pytest.mark.parametrize("count", ["many", -3, True, 12.5, None])
    def test_what_is_not_a_count_of_tokens_is_not_recorded_as_one(self, count):
        """Row 5, a counter-example: the one where `prompt_tokens` is not a count.

        `True` is an `int` to Python and is refused all the same: a provider
        that answered a boolean has not counted anything.
        """
        body = {
            "choices": [{"message": {"content": ANSWER}}],
            "usage": {"prompt_tokens": count, "completion_tokens": 212},
        }

        assert tokens_of(_gemini(body).complete("Extract.")) == Tokens(input=None, output=212)

    def test_a_plain_str_reported_nothing(self):
        """Row 6, a counter-example: the one where a client returns plain text.

        A test's fake does, and it is still a `ModelClient`: a reply is text
        first, and what it cost is extra.
        """
        assert tokens_of(ANSWER) == Tokens(input=None, output=None)

    def test_a_reply_is_the_text_it_carries(self):
        """Rows 1-3: a `Reply` reads as its text wherever text is read."""
        reply = Reply(ANSWER, input_tokens=1204, output_tokens=212)

        assert isinstance(reply, str)
        assert reply == ANSWER
        assert reply.upper() == ANSWER.upper()
