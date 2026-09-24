"""The Jira connector: issues from a JQL query, attachments beside them (spec 001).

Reads, and only reads (R1.1). Every route here is a `GET`: there is no method on
this class that creates, updates, transitions or marks anything as seen, which is
the strongest form the promise takes -- a write is not guarded against, it is
absent.

An issue and the files attached to it are separate addresses (R1.6). An issue is
`INC-4821`; a file it carries is `INC-4821/report.pdf`, and `fetch` takes either,
as spec 001 says. The attachment's own marker is Jira's attachment id: replacing
a file adds a new attachment with a new id, so the id moves exactly when the
bytes do, while the issue sits untouched at its own version (R2.6).

`httpx` is imported inside the functions that use it. A `dossier convert` that
never builds this connector should not pay for the import.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from dossier.domain.conversion import JIRA_ISSUE, reported_media_type
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.sync import server_zone_floor

# Where a listing is asked for depends on the deployment (R1.13). Data Center
# pages `SEARCH` by offset against `total`; Cloud has retired that route and
# pages `SEARCH_CLOUD` by the token each page hands back. Issues and attachments
# are reached the same way on both.
SEARCH = "/rest/api/2/search"
SEARCH_CLOUD = "/rest/api/2/search/jql"
ISSUES = "/rest/api/2/issue"

Deployment = Literal["datacenter", "cloud"]

# What one search asks for. Jira caps this server-side anyway; asking for a page
# at a time and following `total` is what makes the listing complete (R1.3).
PAGE_SIZE = 50

# Generous, and bounded. A search over a large project is slow; a server that
# never answers must end the sync rather than hang it.
TIMEOUT_SECONDS = 60.0

# The fields a listing needs: the key, the version marker, and what is attached.
# Asking for these three rather than everything keeps a listing over a large
# project from carrying every description with it.
LISTED_FIELDS = "updated,attachment"


class JiraRequestFailed(RuntimeError):
    """Jira could not be reached, or did not answer as expected.

    The message names the method, the URL and the status, and never the token:
    that travels in a header, and nothing here echoes a header (R1.8 row 2).
    """


class JiraKeys(BaseModel):
    """The keys a `jira` source takes beyond the shared ones (R1.10).

    `token_env` names the variable holding the credential; the value itself is
    never written here, because `sources.yaml` is committed to git (R1.8).
    `user_env` names the user it is paired with, and naming one is what turns
    the header from Bearer into Basic (R1.12). `deployment` says which Jira is
    behind `url`, and so which listing route to ask (R1.13); absent means Data
    Center, the one this project reads.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    query: str
    token_env: str = ""
    user_env: str = ""
    deployment: Deployment = "datacenter"

    @model_validator(mode="after")
    def _a_user_needs_a_token(self) -> JiraKeys:
        # Half a credential, refused at load time rather than sent as
        # `Basic user:` to a server that will name the wrong cause (R1.12 row 5).
        if self.user_env and not self.token_env:
            raise ValueError("`user_env` names a user with no token: name `token_env` as well")
        return self


class JiraConnector:
    """Issues matching a JQL query, and the files they carry."""

    # `since` becomes a JQL clause, so a windowed listing omits every unchanged
    # issue. Subtracting from one would tombstone the quiet majority of the
    # source; sync asks for `since=None` when it needs the whole (R1.11, R2.22).
    lists_everything = False

    def __init__(
        self,
        *,
        base_url: str,
        query: str,
        token: str | None = None,
        user: str | None = None,
        deployment: Deployment = "datacenter",
        transport: Any | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._query = query
        self._token = token
        self._user = user
        self._deployment = deployment
        self._transport = transport

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        """Every issue the query matches, a page at a time.

        `since` narrows the JQL, and deliberately narrows it *less* than asked:
        Jira reads a bare timestamp in the server's own timezone, which is not
        knowable from here, so the window is widened by a day. Returning extra
        items costs a comparison; omitting one is a document that goes stale with
        nothing to see (R1.4).
        """
        jql = self._query if since is None else f"{self._query} AND {_updated_since(since)}"
        pages = self._cloud_pages(jql) if self._deployment == "cloud" else self._pages(jql)
        for issue in pages:
            yield ItemRef(
                key=issue["key"],
                remote_version=_version_of(issue),
                updated_at=_parsed(issue.get("fields", {}).get("updated")),
            )

    def _pages(self, jql: str) -> Iterator[dict]:
        """Data Center: `SEARCH`, paged by offset until `total` is reached (R1.13 row 1)."""
        start = 0
        while True:
            page = self._get(
                f"{self._base}{SEARCH}",
                params={
                    "jql": jql,
                    "startAt": start,
                    "maxResults": PAGE_SIZE,
                    "fields": LISTED_FIELDS,
                },
            ).json()
            issues = page.get("issues") or []
            yield from issues

            start += len(issues)
            if not issues or start >= int(page.get("total", start)):
                return

    def _cloud_pages(self, jql: str) -> Iterator[dict]:
        """Cloud: `SEARCH_CLOUD`, paged by the token each page hands back (R1.13 row 2).

        A page without a token, or one saying `isLast`, is the last. Cloud
        returns only `id` unless fields are asked for by name, which is why
        `LISTED_FIELDS` is sent here as it is to Data Center.
        """
        params: dict[str, object] = {
            "jql": jql,
            "maxResults": PAGE_SIZE,
            "fields": LISTED_FIELDS,
        }
        while True:
            page = self._get(f"{self._base}{SEARCH_CLOUD}", params=params).json()
            yield from page.get("issues") or []

            token = page.get("nextPageToken")
            if not token or page.get("isLast"):
                return
            params = {**params, "nextPageToken": token}

    def fetch(self, key: str) -> RawItem:
        """The payload at `key`: an issue, or a file one of them carries.

        Returned byte for byte, as received. Jira's JSON is stored as Jira sent
        it -- re-serialising it here would change the content hash of every issue
        for no reason anyone could see afterwards (R1.2). An issue is labelled a
        Jira issue rather than JSON, so the converter that reads it claims Jira
        issues and nothing else (R1.14).
        """
        item, filename = _split(key)
        if filename is None:
            response = self._get(f"{self._base}{ISSUES}/{item}")
            return RawItem(
                key=key,
                payload=response.content,
                media_type=JIRA_ISSUE,
                remote_version=_version_of(response.json()),
            )

        attachment = self._attachment(item, filename)
        response = self._get(attachment["content"])
        return RawItem(
            key=key,
            payload=response.content,
            # What Jira says the file is, not what its name suggests (R2.16,
            # R8.3); which of its two answers wins, and the canonical form, is
            # the domain's.
            media_type=reported_media_type(
                attachment.get("mimeType"), response.headers.get("content-type")
            ),
            remote_version=str(attachment["id"]),
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        """The files `key` carries, each with its own address and marker (R1.6)."""
        for attachment in self._attachments_of(key):
            yield AttachmentRef(
                key=f"{key}/{attachment['filename']}",
                item_key=key,
                remote_version=str(attachment["id"]),
            )

    def _attachments_of(self, key: str) -> list[dict]:
        issue = self._get(f"{self._base}{ISSUES}/{key}", params={"fields": "attachment"}).json()
        return list(issue.get("fields", {}).get("attachment") or [])

    def _attachment(self, key: str, filename: str) -> dict:
        for attachment in self._attachments_of(key):
            if attachment.get("filename") == filename:
                return attachment
        raise JiraRequestFailed(f"{key} carries no attachment named {filename!r}")

    def _get(self, url: str, params: Mapping[str, object] | None = None):
        """One read, or `JiraRequestFailed` naming the URL and what went wrong.

        The only verb this connector has. Adding a `_post` would be adding the
        ability to break R1.1 by typo.
        """
        import httpx

        headers = {"Accept": "application/json"}
        authorization = _authorization(user=self._user, token=self._token)
        if authorization:
            headers["Authorization"] = authorization

        with httpx.Client(
            headers=headers, timeout=TIMEOUT_SECONDS, transport=self._transport
        ) as http:
            try:
                response = http.get(url, params=dict(params or {}))
            except httpx.HTTPError as error:
                raise JiraRequestFailed(f"GET {url} failed: {error}") from None

        if not response.is_success:
            raise JiraRequestFailed(
                f"GET {url} answered {response.status_code} {response.reason_phrase}"
            )
        return response

    @classmethod
    def from_config(
        cls, config, *, workspace: Path, credential: object | None = None
    ) -> JiraConnector:
        """Build from a `sources.yaml` entry (the entry-point contract).

        The credential arrives as an argument, resolved by `dossier.config` --
        the only package that reads the environment. A connector that went
        looking in `os.environ` itself would be a second place credentials come
        from, and R1.8 is the claim that there is one. The layer contract says
        the same thing in the other direction: infrastructure may import the
        domain, and nothing else.
        """
        url = config.options.get("url")
        query = config.options.get("query")
        if not url or not query:
            # Loading has already refused a jira source missing either (R1.10).
            # Checked again because a connector is built from whatever config it
            # is handed, and one built by hand never went through the loader.
            raise ValueError(
                f"source {config.id!r} has type 'jira' and needs both `url` and `query`."
            )

        return cls(
            base_url=url,
            query=query,
            token=getattr(credential, "value", None),
            user=getattr(credential, "user", None),
            deployment=config.options.get("deployment", "datacenter"),
        )


def _authorization(*, user: str | None, token: str | None) -> str | None:
    """The `Authorization` header the keys ask for, or none (R1.12).

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


def _split(key: str) -> tuple[str, str | None]:
    """`INC-4821/report.pdf` as its issue and its filename; an issue key as itself."""
    item, separator, filename = key.partition("/")
    return item, filename if separator else None


def _version_of(issue: Mapping[str, Any]) -> str | None:
    """An issue's version marker: when Jira last updated it.

    `None` when the field was not asked for or not returned, never a fetch time:
    a fabricated marker makes R2.1 skip an item that really did change, and
    nothing downstream can detect it (R1.5).
    """
    updated = issue.get("fields", {}).get("updated")
    return str(updated) if updated else None


def _parsed(updated: str | None) -> datetime | None:
    """Jira's `2026-08-05T16:02:00.000+0000` as a datetime, or `None` if unreadable.

    `None` rather than a guess: `updated_at` is advisory, and an unparsed string
    is better reported as absent than as a time nobody can vouch for.
    """
    if not updated:
        return None
    try:
        return datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
    except ValueError:
        return None


def _updated_since(since: datetime) -> str:
    """The JQL clause narrowing a search, from the floor the domain sets (R1.4).

    Jira reads `updated >= "2026-08-04 09:00"` in the server's timezone, which
    is not knowable from here; how much slack that needs is decided in
    `domain.sync`, and this only spells the clause.
    """
    return f'updated >= "{server_zone_floor(since).strftime("%Y-%m-%d %H:%M")}"'


# The entry point resolves to `JiraConnector.from_config`, and a bound method
# reads its attributes from the function beneath it -- so this is where the
# registry finds the declaration (R1.10), with no change to the entry point.
JiraConnector.from_config.__func__.keys = JiraKeys
