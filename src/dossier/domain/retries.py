"""When a model request is sent again, and how long to wait first (R9.17).

A rate limit is not an answer about the document, so a request refused by a
busy server is sent again, unchanged, before the stage ever sees a failure.
Which answers qualify is a decision, and it lives here rather than beside the
HTTP call that acts on it: a list of statuses tucked into a client is exactly
the decision no test can reach without a server.

The policy is both official SDKs' (openai-python, anthropic-sdk-python), value
for value, rather than numbers chosen here.
"""

from __future__ import annotations


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
