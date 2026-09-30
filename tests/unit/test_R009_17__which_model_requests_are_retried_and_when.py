"""R9.17 — a model request answered 408, 409, 429 or 5xx, or not answered at all,
is sent again up to twice before it fails.

The decisions, without a client or a server: which answers are worth the same
request again, and how long to wait before sending it. Both are pure, so the
jitter and the clock arrive as arguments and every row is an exact assertion.
The list and the numbers are both official SDKs', value for value.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from dossier.domain.retries import retry_after, retryable, wait_before

NOW = datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC)


class TestWhichAnswersAreSentAgain:
    """R9.17 — which answers are retried: rows 1, 3, 4, 5, 7 and 8."""

    @pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504, 529])
    def test_an_answer_the_server_may_not_give_again_is_retried(self, status: int):
        """Rows 1, 3 and 5: the one where the server is busy rather than refusing.

        529 is Anthropic's "overloaded", and a 5xx like any other: the policy is
        every provider's, not one client's.
        """
        assert retryable(status)

    def test_no_answer_at_all_is_retried(self):
        """Row 4: the one where no server answered -- refused, reset or timed out."""
        assert retryable(None)

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 499])
    def test_an_answer_that_would_come_back_the_same_is_not(self, status: int):
        """Rows 7 and 8, counter-examples: the one where asking again changes nothing.

        A key refused once is refused again, and a request the server could not
        read is not re-read. Sending either twice only doubles the refusal. 499
        is the last status below "every 5xx", and a client's like the others.
        """
        assert not retryable(status)


class TestHowLongToWait:
    """R9.17 — how long to wait before sending it again: rows 2, 3 and 6."""

    def test_the_server_says_how_long(self):
        """Row 2: the one where the 429 carries `Retry-After: 3`."""
        asked = retry_after({"Retry-After": "3"}, now=NOW)
        assert wait_before(1, retry_after=asked, jitter=1.0) == 3.0

    def test_a_wait_in_milliseconds_is_read_too(self):
        """Row 2, in the form OpenAI sends: `retry-after-ms`, preferred when both are there."""
        headers = {"retry-after-ms": "1500", "retry-after": "3"}
        assert retry_after(headers, now=NOW) == 1.5

    def test_a_wait_given_as_a_date_is_counted_from_now(self):
        """Row 2, in HTTP's other form: a date, three seconds after the clock handed in."""
        assert retry_after({"Retry-After": "Thu, 06 Aug 2026 09:00:03 GMT"}, now=NOW) == 3.0

    def test_with_nothing_said_the_wait_doubles_from_half_a_second(self):
        """Row 3: the one where the 503s carry no `Retry-After`, with no jitter taken."""
        waits = [wait_before(retry, retry_after=None, jitter=1.0) for retry in (1, 2)]
        assert waits == [0.5, 1.0]

    def test_the_backoff_is_capped_at_eight_seconds(self):
        """Row 3's boundary: the doubling stops at 8 s, as both SDKs stop it."""
        assert wait_before(6, retry_after=None, jitter=1.0) == 8.0

    def test_the_jitter_shortens_the_backoff_and_never_lengthens_it(self):
        """Row 3: each wait is shortened by up to a quarter, so callers refused together
        do not come back together."""
        assert wait_before(2, retry_after=None, jitter=0.75) == 0.75

    @pytest.mark.parametrize("seconds", ["120", "61"])
    def test_a_wait_longer_than_a_minute_is_not_waited_for(self, seconds: str):
        """Row 6, a counter-example: the one where the 429 asks for two minutes.

        Both SDKs use their own backoff instead, and a server asking for longer is
        a quota rather than a burst. 61 is the first whole second past the limit.
        """
        asked = retry_after({"Retry-After": seconds}, now=NOW)
        assert wait_before(1, retry_after=asked, jitter=1.0) == 0.5

    def test_a_wait_of_exactly_a_minute_is_waited_for(self):
        """Row 6's boundary: 60 s is the longest wait honoured, and it is honoured."""
        assert wait_before(1, retry_after=60.0, jitter=1.0) == 60.0

    def test_a_wait_under_a_second_is_waited_for(self):
        """Row 2's other boundary: any wait above 0 is the server's to ask for.

        `retry-after-ms: 250` is shorter than the backoff would wait, and it is
        still the server's wait that is kept.
        """
        asked = retry_after({"retry-after-ms": "250"}, now=NOW)
        assert wait_before(1, retry_after=asked, jitter=1.0) == 0.25

    @pytest.mark.parametrize("value", ["0", "-2", "soon", ""])
    def test_a_wait_that_is_not_a_wait_falls_back_to_the_backoff(self, value: str):
        """Row 6's other side: the one where `Retry-After` says nothing usable."""
        asked = retry_after({"Retry-After": value}, now=NOW)
        assert wait_before(1, retry_after=asked, jitter=1.0) == 0.5

    def test_no_header_is_no_wait_asked_for(self):
        """Row 3: the one where the server says nothing about waiting."""
        assert retry_after({}, now=NOW) is None


class Server:
    """A model endpoint answering from a script -- a response, or an exception to
    raise -- and then `ok`. Remembers every request, because the rows count them."""

    def __init__(self, *script: httpx.Response | Exception, ok: httpx.Response) -> None:
        self.script = list(script)
        self.ok = ok
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.script:
            return self.ok
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


OPENAI_OK = httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
ANTHROPIC_OK = httpx.Response(
    200, json={"content": [{"type": "text", "text": "answer"}], "stop_reason": "end_turn"}
)


class TestEveryClientSendsItAgain:
    """R9.17 — the resend itself, where every model client sends: rows 4, 5 and 8."""

    def test_a_request_no_server_answered_is_sent_again(self):
        """Row 4: the one where the connection is refused, then answered."""
        from dossier.infrastructure.models.openai_compatible import gemini

        refused = httpx.ConnectError("connection refused")
        server = Server(refused, ok=OPENAI_OK)
        waits: list[float] = []
        client = gemini(
            "gemini:gemini-3.5-flash-lite",
            url="http://localhost:8080/api",
            transport=server.transport,
            sleep=waits.append,
        )

        assert client.complete("Extract the fields.") == "answer"
        assert len(server.requests) == 2
        assert len(waits) == 1

    def test_an_overloaded_anthropic_is_asked_again(self):
        """Row 5: the one where Anthropic answers 529, then 200."""
        from dossier.infrastructure.models.anthropic import anthropic

        server = Server(httpx.Response(529), ok=ANTHROPIC_OK)
        waits: list[float] = []
        client = anthropic(
            "anthropic:claude-sonnet-4-5-20250929",
            url="https://api.anthropic.com/v1",
            transport=server.transport,
            sleep=waits.append,
        )

        assert client.complete("Extract the fields.") == "answer"
        assert len(server.requests) == 2
        assert server.requests[0].content == server.requests[1].content

    def test_a_request_the_server_could_not_read_is_not_sent_again(self):
        """Row 8, a counter-example: the one where the answer is 400."""
        from dossier.infrastructure.models.ollama import ModelRequestFailed, ollama

        server = Server(httpx.Response(400), ok=httpx.Response(200))
        waits: list[float] = []
        client = ollama(
            "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8,
            url="http://localhost:11434",
            transport=server.transport,
            sleep=waits.append,
        )
        client._unchecked = False  # the digest check is R9.4's, not this row's

        with pytest.raises(ModelRequestFailed) as error:
            client.complete("Extract the fields.")

        assert len(server.requests) == 1
        assert waits == []
        assert "400" in str(error.value)
        assert "attempts" not in str(error.value)
