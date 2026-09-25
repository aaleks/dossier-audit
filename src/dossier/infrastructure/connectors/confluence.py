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

from dossier.domain.conversion import reported_media_type
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.sync import server_zone_floor

SEARCH = "/rest/api/content/search"
CONTENT = "/rest/api/content"

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

        for page in self._results(f"{self._base}{SEARCH}", {"cql": cql, "expand": "version"}):
            # The id, never the title: a rename would otherwise be a
            # tombstone and a new item rather than an edit (R1.16, R2.7).
            yield ItemRef(
                key=str(page["id"]),
                remote_version=_version_of(page),
                updated_at=_when(page),
            )

    def fetch(self, key: str) -> RawItem:
        """The payload at `key`: a file a page carries.

        Returned byte for byte, as received (R1.2), and labelled with what
        Confluence records the file as, over what the transport said while
        sending it (R2.16).
        """
        page, filename = _split(key)
        attachment = self._attachment(page, filename)
        response = self._get(f"{self._base}{attachment['_links']['download']}")
        return RawItem(
            key=key,
            payload=response.content,
            media_type=reported_media_type(
                (attachment.get("extensions") or {}).get("mediaType"),
                response.headers.get("content-type"),
            ),
            remote_version=_file_version_of(attachment),
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        """The files page `key` carries, each with its own address and marker (R1.18)."""
        for attachment in self._attachments_of(key):
            yield AttachmentRef(
                key=f"{key}/{attachment['title']}",
                item_key=key,
                remote_version=_file_version_of(attachment),
            )

    def _attachments_of(self, key: str) -> Iterator[dict]:
        yield from self._results(
            f"{self._base}{CONTENT}/{key}/child/attachment", {"expand": "version"}
        )

    def _attachment(self, key: str, filename: str | None) -> dict:
        for attachment in self._attachments_of(key):
            if attachment.get("title") == filename:
                return attachment
        raise ConfluenceRequestFailed(f"page {key} carries no file named {filename!r}")

    def _results(self, url: str, params: Mapping[str, object]) -> Iterator[dict]:
        """Every result a paged answer holds, asked for `PAGE_SIZE` at a time.

        Search and a page's files page the same way: by `start` and `limit`,
        until an answer names no `next` (R1.15, R1.18). An empty page of
        results ends it too, so a server that always names one cannot loop.
        """
        start = 0
        while True:
            answer = self._get(
                url, params={**params, "start": start, "limit": PAGE_SIZE}
            ).json()
            results = answer.get("results") or []
            yield from results

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
                # `None` rather than `{}` when there are none: httpx replaces a
                # URL's own query with `params`, and a file's download link
                # carries the version it names in its query (R1.18).
                response = http.get(url, params=dict(params) if params else None)
            except httpx.HTTPError as error:
                raise ConfluenceRequestFailed(f"GET {url} failed: {error}") from None

        if not response.is_success:
            raise ConfluenceRequestFailed(
                f"GET {url} answered {response.status_code} {response.reason_phrase}"
            )
        return response


def _version_of(page: Mapping[str, Any]) -> str | None:
    """A page's marker: Confluence's version number, written `v37` (R1.16).

    `None` when the answer carries no number, never a fetch time: a made-up
    marker makes R2.1 skip a page that did change (R1.5).
    """
    number = (page.get("version") or {}).get("number")
    return f"v{number}" if number is not None else None


def _file_version_of(attachment: Mapping[str, Any]) -> str | None:
    """A file's marker: its attachment id and version, `81920301:v2` (R1.18).

    Both, because each alone misses a case. Uploading again under the same name
    keeps the id and raises the version; deleting and uploading again makes a
    new id and starts the version at 1 again.
    """
    number = (attachment.get("version") or {}).get("number")
    return f"{attachment['id']}:v{number}" if number is not None else None


def _split(key: str) -> tuple[str, str | None]:
    """`81920114/escalation-matrix.png` as its page and its filename; a page id as itself."""
    page, separator, filename = key.partition("/")
    return page, filename if separator else None


def _when(page: Mapping[str, Any]) -> datetime | None:
    """When the page's version was written, or `None` if that is unreadable.

    Advisory, as a Jira issue's `updated` is: an unparsed string is better
    reported as absent than as a time nobody can vouch for.
    """
    when = (page.get("version") or {}).get("when")
    if not when:
        return None
    try:
        return datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError:
        return None


def _modified_since(since: datetime) -> str:
    """The CQL clause narrowing a search, from the floor the domain sets (R1.4)."""
    return f'lastmodified >= "{server_zone_floor(since).strftime("%Y-%m-%d %H:%M")}"'
