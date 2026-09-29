"""What every model client does the same way over HTTP (spec 009).

One place decides how a key is sent and what a failed request says, so no
client can drift into echoing a key in an error (R9.8 row 1). The clients differ
only in the route they call and the shape of the body; how a request is made,
refused or unreachable is written here once.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dossier.domain.refusals import refusal_reason
from dossier.domain.retries import MAX_RETRIES, retry_after, retryable, wait_before
from dossier.domain.usage import counted

if TYPE_CHECKING:
    from dossier.domain.ports import ImagePart

import httpx

# A model can take minutes over a long document, and httpx's own default of five
# seconds would fail nearly every real request. Generous rather than unbounded,
# so a server that never answers still ends the run instead of hanging it.
TIMEOUT_SECONDS = 300.0

# What httpx raises when no server answered: refused, reset, or timed out. Such a
# request may be answered next time (R9.17 row 4). Anything else it raises -- a
# URL it cannot send to at all -- would fail the same way twice.
NO_ANSWER = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)

Sleep = Callable[[float], None]


class ModelRequestFailed(RuntimeError):
    """A model endpoint could not be reached, or did not answer as expected.

    The message names the URL, the status, and the reason the provider gave for
    a refusal (R9.22). It never carries the key: that is sent only in a request
    header, nothing here echoes a header, and a reason quoting it has it removed
    (R9.8 row 1).
    """


def http_client(
    api_key: str | None, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """A client sending `api_key` as a bearer token, or no `Authorization` header at all.

    No header rather than an empty bearer token: a local server with no auth may
    reject `Authorization: Bearer ` as malformed.
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return httpx.Client(headers=headers, timeout=TIMEOUT_SECONDS, transport=transport)


def request(
    http: httpx.Client, method: str, url: str, *, sleep: Sleep = time.sleep, **kwargs
) -> httpx.Response:
    """One answer, or `ModelRequestFailed` naming the URL and what went wrong.

    A busy server's refusal, or no answer at all, is not the end: the request is
    sent again, unchanged, at most twice, waiting as the domain decides (R9.17).
    All of it happens inside this one call, so the stage above sees one answer
    and counts one call (R5.5). A refusal that would come back the same -- a
    `401`, a `400` -- fails on the first answer.

    `sleep` is the wait, handed in so a test about waiting three seconds takes
    none. The jitter is drawn here, the one place randomness is allowed near it.
    """
    attempt = 1
    while True:
        try:
            response = http.request(method, url, **kwargs)
        except NO_ANSWER as error:
            status, headers, reason = None, {}, None
            failure = f"{method} {url} failed: {error}"
        except httpx.HTTPError as error:
            raise ModelRequestFailed(f"{method} {url} failed: {error}") from None
        else:
            if response.is_success:
                return response
            status, headers = response.status_code, response.headers
            failure = f"{method} {url} answered {status} {response.reason_phrase}"
            reason = refusal_reason(response.content, secrets=_keys(http))
        if attempt > MAX_RETRIES or not retryable(status):
            # How many were made, once there was more than one: "answered 503"
            # alone would read as a server that refused the only request sent.
            tried = f" (after {attempt} attempts)" if attempt > 1 else ""
            # And why, last: it is the provider's sentence, and may run long.
            said = f": {reason}" if reason else ""
            raise ModelRequestFailed(failure + tried + said)
        asked = retry_after(headers, now=datetime.now(UTC))
        sleep(wait_before(attempt, retry_after=asked, jitter=1 - 0.25 * random.random()))
        attempt += 1


def _keys(http: httpx.Client) -> list[str]:
    """The key this client sends, however its provider takes it, so no reason repeats it."""
    sent = (http.headers.get("authorization", ""), http.headers.get("x-api-key", ""))
    return [value.removeprefix("Bearer ").strip() for value in sent if value]


def text_at(response: httpx.Response, *path: str | int) -> str:
    """The string at `path` in a JSON answer, or `ModelRequestFailed` saying where not.

    Returned verbatim: validating a model's answer is the stage's job (R6.1), and
    a client that reshaped it would validate something the model never said.
    """
    try:
        value = response.json()
        for step in path:
            value = value[step]
    except (ValueError, KeyError, IndexError, TypeError):
        value = None
    if not isinstance(value, str):
        # `choices[0].message.content`, spelled as the API documents it.
        where = "".join(
            f"[{step}]" if isinstance(step, int) else f".{step}" for step in path
        ).lstrip(".")
        raise ModelRequestFailed(
            f"{response.request.method} {response.request.url} answered "
            f"{response.status_code} with no {where}"
        )
    return value


def count_at(response: httpx.Response, *path: str) -> int | None:
    """The token count at `path` in a JSON answer, or `None` where there is none (R9.18).

    Absent, malformed or not a count at all, it is `None`: an answer that did not
    say what it cost is recorded as not saying, never as costing nothing.
    """
    try:
        value = response.json()
        for step in path:
            value = value[step]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return counted(value)


def encoded(part: ImagePart) -> str:
    """One part's bytes as base64 ascii (R9.16).

    Shared by all three providers because all three carry images as base64 and
    differ only in where they put them. Encoding it three times would be three
    chances to differ over padding.
    """
    import base64

    return base64.b64encode(part.data).decode("ascii")
