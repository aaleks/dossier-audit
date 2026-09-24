"""When a model request is sent again, and how long to wait first (R9.17).

A rate limit is not an answer about the document, so a request refused by a
busy server is sent again, unchanged, before the stage ever sees a failure.
Which answers qualify is a decision, and it lives here rather than beside the
HTTP call that acts on it: a list of statuses tucked into a client is exactly
the decision no test can reach without a server.

The policy is both official SDKs' (openai-python, anthropic-sdk-python), value
for value, rather than numbers chosen here. The random part of a wait and the
time it is now arrive as arguments, so every answer below is exact.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from email.utils import parsedate_to_datetime

# At most this many requests after the first. The SDKs' default.
MAX_RETRIES = 2

# The backoff when the server says nothing: 0.5 s, then 1 s, doubling, capped.
INITIAL_WAIT = 0.5
MAX_WAIT = 8.0

# The longest wait a server may ask for and be obeyed. Asked for more, the SDKs
# fall back to their own backoff rather than hold a caller for minutes, and so
# does dossier: a server wanting two minutes is describing a quota, not a burst.
LONGEST_WAIT_HONOURED = 60.0


def retryable(status: int | None) -> bool:
    """Whether an answer -- or no answer, `None` -- is worth the same request again.

    `408`, `409`, `429` and every `5xx` say the server could not take the request
    *now*; Anthropic's `529` "overloaded" is one of them. A request no server
    answered at all -- refused, reset or timed out -- may be answered next time.
    Anything else, a `401` above all, would come back the same, and sending it
    twice would only double the refusal.
    """
    if status is None:
        return True
    return status in (408, 409, 429) or status >= 500


def retry_after(headers: Mapping[str, str], *, now: datetime) -> float | None:
    """How long the server asked to be left alone, in seconds, or `None` if it did not say.

    Three forms, read as the SDKs read them: OpenAI's `retry-after-ms` first, then
    `Retry-After` as seconds, then `Retry-After` as an HTTP date, counted from
    `now`. Anything else is not a wait, and the backoff decides instead. A wait
    is returned as the server said it, zero and less included: whether it is
    worth obeying is `wait_before`'s decision, not the reader's.
    """
    lowered = {name.lower(): value for name, value in headers.items()}
    if (millis := _number(lowered.get("retry-after-ms"))) is not None:
        return millis / 1000
    value = lowered.get("retry-after")
    if value is None:
        return None
    if (seconds := _number(value)) is not None:
        return seconds
    try:
        return (parsedate_to_datetime(value) - now).total_seconds()
    except (TypeError, ValueError, IndexError):
        return None


def wait_before(retry: int, *, retry_after: float | None, jitter: float) -> float:
    """Seconds to wait before sending the request again for the `retry`th time.

    The server's own wait when it gave one worth obeying -- above zero and no
    longer than a minute. Otherwise the backoff, `0.5 s * 2**(retry - 1)` capped
    at 8 s, times `jitter`: a draw in `(0.75, 1.0]` handed in by the caller, so
    that callers refused together do not all come back together, and so that
    this function stays exact.
    """
    if retry_after is not None and 0 < retry_after <= LONGEST_WAIT_HONOURED:
        return retry_after
    return min(INITIAL_WAIT * 2 ** (retry - 1), MAX_WAIT) * jitter


def _number(value: str | None) -> float | None:
    """`value` as a number of seconds or milliseconds, or `None` if it is not one."""
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
