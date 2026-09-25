"""The Confluence connector: pages from a CQL query, and the files they carry (spec 001).

Reads, and only reads (R1.1). Every route here is a `GET`: as in the Jira
connector, there is no method on this class that creates, edits, moves or marks
anything, so a write is not guarded against -- it is absent.

Read against Confluence Data Center 9.2 (spec 001, "A Confluence page").

`httpx` is imported inside the functions that use it. A `dossier convert` that
never builds this connector should not pay for the import.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from dossier.domain.ports import ItemRef
from dossier.domain.sync import server_zone_floor

SEARCH = "/rest/api/content/search"

# What one search asks for. Confluence caps it server-side anyway; asking for a
# page of results at a time and following `next` is what makes the listing
# complete (R1.3).
PAGE_SIZE = 50

# Generous, and bounded, as the Jira connector's is: a server that never
# answers must end the sync rather than hang it.
TIMEOUT_SECONDS = 60.0


class ConfluenceRequestFailed(RuntimeError):
    """Confluence could not be reached, or did not answer as expected.

    The message names the method, the URL and the status, and never a
    credential: that travels in a header, and nothing here echoes a header.
    """


class ConfluenceKeys(BaseModel):
    """The keys a `confluence` source takes beyond the shared ones (R1.10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    query: str


class ConfluenceConnector:
    """Pages matching a CQL query."""

    # `since` becomes a CQL clause, so a windowed listing omits every unchanged
    # page, and subtracting from one would tombstone most of the space (R1.11).
    lists_everything = False

    def __init__(self, *, base_url: str, query: str, transport: Any | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._query = query
        self._transport = transport

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        """Every page the query matches, a page of results at a time (R1.15).

        `type = page` is added to the query, parenthesised so an `OR` in it
        stays inside: CQL matches comments and attachments as readily as pages.
        `since` narrows it less than asked, as a Jira window is, because CQL
        reads a bare time in the server's own zone (R1.4).
        """
        cql = f"({self._query}) AND type = page"
        if since is not None:
            cql = f"{cql} AND {_modified_since(since)}"

        start = 0
        while True:
            answer = self._get(
                f"{self._base}{SEARCH}",
                params={"cql": cql, "start": start, "limit": PAGE_SIZE, "expand": "version"},
            ).json()
            results = answer.get("results") or []
            for page in results:
                yield ItemRef(key=str(page["id"]), remote_version=None, updated_at=None)

            start += len(results)
            if not results or "next" not in (answer.get("_links") or {}):
                return

    def _get(self, url: str, params: Mapping[str, object] | None = None):
        """One read, or `ConfluenceRequestFailed` naming the URL and what went wrong."""
        import httpx

        with httpx.Client(
            headers={"Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
            transport=self._transport,
        ) as http:
            try:
                response = http.get(url, params=dict(params or {}))
            except httpx.HTTPError as error:
                raise ConfluenceRequestFailed(f"GET {url} failed: {error}") from None

        if not response.is_success:
            raise ConfluenceRequestFailed(
                f"GET {url} answered {response.status_code} {response.reason_phrase}"
            )
        return response


def _modified_since(since: datetime) -> str:
    """The CQL clause narrowing a search, from the floor the domain sets (R1.4)."""
    return f'lastmodified >= "{server_zone_floor(since).strftime("%Y-%m-%d %H:%M")}"'
