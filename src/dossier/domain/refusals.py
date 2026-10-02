"""Why a model provider refused a request, as its answer says (R9.22).

`400 Bad Request` says a request was refused and not why, and the why is
usually one sentence the provider already wrote: on 2026-09-29 every judge call
to Anthropic answered 400, and the cause -- a schema left open -- was in the
body nobody printed (R9.21).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

# Where each provider writes its reason, in the order they are looked for.
# `error.message` is OpenAI's, Anthropic's and vLLM's; `error` as a string is
# Ollama's; `detail` is OpenWebUI's, a FastAPI app's.
_KEYS = ("message", "detail")


def refusal_reason(body: bytes, *, secrets: Sequence[str] = ()) -> str | None:
    """The reason a refusal gives, on one line, or `None` when it gives none.

    A body that is not JSON -- a proxy's HTML error page -- is not a reason, and
    is left out rather than printed a hundred lines long. Every secret is removed
    wherever the provider quoted it: a key goes in a request header and nowhere
    else, whatever the answer repeats (R9.8).
    """
    try:
        answer = json.loads(body)
    except ValueError:
        return None
    said = _said(answer)
    if said is None:
        return None
    reason = " ".join(said.split())
    for secret in secrets:
        if secret:
            reason = reason.replace(secret, "***")
    return reason or None


def _said(answer: object) -> str | None:
    if not isinstance(answer, dict):
        return None
    error = answer.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str):
        return error
    return next((answer[key] for key in _KEYS if isinstance(answer.get(key), str)), None)


# What a provider answers a request it refused as sent: malformed, too large
# for the model's window, or not processable as it stands (R9.23). Another
# request -- another document's -- may be answered.
REFUSED_AS_SENT = (400, 413, 422)


def about_the_request(status: int | None) -> bool:
    """Whether a refusal is about this request as sent, rather than the endpoint (R9.23).

    `400`, `413` and `422` are. `401` and `403` are about a key, `404` about a
    model or a URL, `408`, `409`, `429` and `5xx` about the endpoint now
    (R9.17), and no answer at all about the network: none is the document's,
    and no other request would get past it.
    """
    return status in REFUSED_AS_SENT


class UnanswerableRequest(RuntimeError):
    """A request refused as sent, or a reply cut off at its limit (R9.23, R9.24).

    About this request and not the endpoint, so a stage fails the document it
    asked about and the run goes on. Anything that does not catch it as one
    stops the command, as any model failure does (R9.25).
    """


# Each provider's word for a reply that stopped at its output limit (R9.24):
# OpenAI-compatible endpoints and Ollama say `length`, Anthropic `max_tokens`.
_CUT_OFF = ("length", "max_tokens")


def cut_off(stopped: object) -> bool:
    """Whether a reply stopped because it reached the model's output limit (R9.24)."""
    return stopped in _CUT_OFF


def cut_off_line(model: str, said: str, stopped: object) -> str:
    """Why a reply cut off at its limit is no answer, in the provider's own words (R9.24)."""
    return f'{model} cut its reply off at its output limit ({said} "{stopped}")'
