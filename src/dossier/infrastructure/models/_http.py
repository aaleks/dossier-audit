"""What every model client does the same way over HTTP (spec 009).

One place decides how a key is sent and what a failed request says, so no
client can drift into echoing a key in an error (R9.8 row 1). The clients differ
only in the route they call and the shape of the body; how a request is made,
refused or unreachable is written here once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dossier.domain.ports import ImagePart

import httpx

# A model can take minutes over a long document, and httpx's own default of five
# seconds would fail nearly every real request. Generous rather than unbounded,
# so a server that never answers still ends the run instead of hanging it.
TIMEOUT_SECONDS = 300.0


class ModelRequestFailed(RuntimeError):
    """A model endpoint could not be reached, or did not answer as expected.

    The message names the URL and the status. It never carries the key: that is
    sent only in a request header, and nothing here echoes a header (R9.8 row 1).
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


def request(http: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """One request, or `ModelRequestFailed` naming the URL and what went wrong."""
    try:
        response = http.request(method, url, **kwargs)
    except httpx.HTTPError as error:
        raise ModelRequestFailed(f"{method} {url} failed: {error}") from None
    if not response.is_success:
        raise ModelRequestFailed(
            f"{method} {url} answered {response.status_code} {response.reason_phrase}"
        )
    return response


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


def encoded(part: ImagePart) -> str:
    """One part's bytes as base64 ascii (R9.16).

    Shared by all three providers because all three carry images as base64 and
    differ only in where they put them. Encoding it three times would be three
    chances to differ over padding.
    """
    import base64

    return base64.b64encode(part.data).decode("ascii")
