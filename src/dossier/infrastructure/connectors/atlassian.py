"""What the Jira and Confluence connectors share: how a source's keys become a header.

One function, so the two connectors cannot come to authenticate differently
(R1.12, R1.21).
"""

from __future__ import annotations

import base64


def authorization(*, user: str | None, token: str | None) -> str | None:
    """The `Authorization` header the keys ask for, or none (R1.12, R1.21).

    A token alone is Bearer, what Data Center takes a personal access token as.
    A user beside it is Basic, the only form Cloud accepts an API token in and
    what Data Center takes a username and password as. Decided once from the
    configuration, never by trying one and then the other: a refusal is a 401
    naming the URL, and the fix is a key in `sources.yaml`.
    """
    if not token:
        return None
    if user:
        pair = base64.b64encode(f"{user}:{token}".encode()).decode("ascii")
        return f"Basic {pair}"
    return f"Bearer {token}"
