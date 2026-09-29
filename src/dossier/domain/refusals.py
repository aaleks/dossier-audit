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
