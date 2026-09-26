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
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from dossier.domain.confluence import export_version
from dossier.domain.conversion import CONFLUENCE_PAGE, reported_media_type
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.sync import server_zone_floor
from dossier.infrastructure.connectors.atlassian import authorization

SEARCH = "/rest/api/content/search"
CONTENT = "/rest/api/content"

# What a page is fetched with: the body as Confluence renders it for export, and
# what the note is headed with (R1.17, R8.19). `export_view` rather than
# `storage`, whose macros only Confluence knows how to draw.
PAGE_EXPAND = "body.export_view,version,space"

# The PDF export (R1.19). A user-interface action, not a REST route: Confluence
# runs it only for a request carrying `EXPORT_HEADERS`, answers with a redirect
# to a file under `/download/export/`, and serves that file to the session that
# asked for it. A page's export is keyed `<page id>.pdf`.
EXPORT = "/spaces/flyingpdf/pdfpageexport.action"
EXPORT_HEADERS = {"X-Atlassian-Token": "no-check", "Accept": "application/pdf"}
EXPORT_SUFFIX = ".pdf"
# What an export is, once its bytes have shown it is one.
PDF_SIGNATURE = b"%PDF-"
EXPORTED_AS = "application/pdf"

Export = Literal["pdf"]

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
    """The keys a `confluence` source takes beyond the shared ones (R1.10).

    `token_env` and `user_env` name the variables holding the credential, read
    as a Jira source reads them (R1.21); the values are never written here,
    because `sources.yaml` is committed to git (R1.8). `export: pdf` asks for
    each page's PDF export beside it (R1.19).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    query: str
    token_env: str = ""
    user_env: str = ""
    export: Export | None = None

    @model_validator(mode="after")
    def _a_user_needs_a_token(self) -> ConfluenceKeys:
        # Half a credential, refused at load time as a Jira source's is (R1.21).
        if self.user_env and not self.token_env:
            raise ValueError("`user_env` names a user with no token: name `token_env` as well")
        return self


class ConfluenceConnector:
    """Pages matching a CQL query, the files they carry, and their PDF exports if asked."""

    # `since` becomes a CQL clause, so a windowed listing omits every unchanged
    # page, and subtracting from one would tombstone most of the space (R1.11).
    lists_everything = False

    def __init__(
        self,
        *,
        base_url: str,
        query: str,
        token: str | None = None,
        user: str | None = None,
        export: Export | None = None,
        transport: Any | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._query = query
        self._export = export
        # Decided once, by the one function Jira's connector uses (R1.21).
        self._authorization = authorization(user=user, token=token)
        self._transport = transport
        # Each listed page's marker, kept so that an export's marker does not
        # cost a request for a version the listing already said (R1.19).
        self._versions: dict[str, str | None] = {}
        # Each page's files as listed this sync, by page (R1.18 row 6).
        self._files: dict[str, list[dict]] = {}

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
            key = str(page["id"])
            self._versions[key] = _version_of(page)
            yield ItemRef(key=key, remote_version=self._versions[key], updated_at=_when(page))

    def fetch(self, key: str) -> RawItem:
        """The payload at `key`: a page, or a file one of them carries.

        Returned byte for byte, as received (R1.2). A page is its JSON rendered
        for export, table of contents and all, labelled a Confluence page so
        the converter reading it claims nothing else (R1.17). A file is
        labelled with what Confluence records it as, over what the transport
        said while sending it (R2.16).
        """
        exported = _exported(key)
        if exported is not None:
            return self._exported(key, exported)

        page, filename = _split(key)
        if filename is None:
            response = self._get(
                f"{self._base}{CONTENT}/{page}", params={"expand": PAGE_EXPAND}
            )
            return RawItem(
                key=key,
                payload=response.content,
                media_type=CONFLUENCE_PAGE,
                remote_version=_version_of(response.json()),
            )

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
        """The files page `key` carries, each with its own address and marker (R1.18).

        With `export: pdf`, its PDF export as well, keyed `<page id>.pdf`
        (R1.19). It is carried by the page as a file is, so it is tombstoned
        with the page, and when `export:` is taken away (R2.6 row 3).
        """
        files = [
            AttachmentRef(
                key=f"{key}/{attachment['title']}",
                item_key=key,
                remote_version=_file_version_of(attachment),
            )
            for attachment in self._attachments_of(key)
        ]
        yield from files
        if self._export == "pdf":
            yield AttachmentRef(
                key=f"{key}{EXPORT_SUFFIX}",
                item_key=key,
                remote_version=export_version(
                    self._version(key), [ref.remote_version for ref in files]
                ),
            )

    def _exported(self, key: str, page: str) -> RawItem:
        """Page `page` as the PDF Confluence exports it (R1.19).

        One client for both requests: the action sets the session cookie that
        the file it redirects to is served under.
        """
        import httpx

        url = f"{self._base}{EXPORT}"
        with httpx.Client(
            headers=self._headers(EXPORT_HEADERS),
            timeout=TIMEOUT_SECONDS,
            transport=self._transport,
            follow_redirects=True,
        ) as http:
            try:
                response = http.get(url, params={"pageId": page})
            except httpx.HTTPError as error:
                raise ConfluenceRequestFailed(f"GET {url} failed: {error}") from None

        # Reported, never worked around (R1.20). `export: pdf` says the server
        # exports; when it does not, the fix is that key or a permission on the
        # server, and asking again another way would make a refusal mean two
        # things. Failing this one document keeps the page and its files, and
        # holds the watermark back, so the refusal is seen at every sync (R2.8).
        asked = f"GET {url}?pageId={page}"
        if response.status_code in (401, 403):
            raise ConfluenceRequestFailed(
                f"{asked} answered {response.status_code} {response.reason_phrase}: "
                "`export: pdf` asks for an export this server refuses. Take `export:` "
                "out of the source, or have the export permission granted."
            )
        if not response.is_success:
            raise ConfluenceRequestFailed(
                f"{asked} answered {response.status_code} {response.reason_phrase}"
            )
        # A server that wants a login redirects to its login page, which answers
        # `200`. Stored, it would be a web page kept and converted as a PDF. The
        # bytes decide, not the header: a PDF begins with its signature whatever
        # a server calls it, and a login page never does.
        if not response.content.startswith(PDF_SIGNATURE):
            sent = reported_media_type(None, response.headers.get("content-type"))
            raise ConfluenceRequestFailed(
                f"{asked} answered {sent}, not a PDF: the export was not made, "
                "and a login page is what a server that wants one sends instead."
            )
        return RawItem(
            key=key, payload=response.content, media_type=EXPORTED_AS, remote_version=None
        )

    def _headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        """`headers`, with the source's `Authorization` when it names a credential."""
        if self._authorization is None:
            return dict(headers)
        return {**headers, "Authorization": self._authorization}

    def _version(self, key: str) -> str | None:
        """Page `key`'s marker: the one its listing said, or asked for if it was not listed."""
        if key not in self._versions:
            answer = self._get(f"{self._base}{CONTENT}/{key}", params={"expand": "version"})
            self._versions[key] = _version_of(answer.json())
        return self._versions[key]

    def _attachments_of(self, key: str) -> list[dict]:
        """The files page `key` carries, listed once for this connector (R1.18 row 6).

        A connector is built for one sync, so the list is that sync's. Listing
        it again for every file fetched cost KIP-1279's 66 images about 130
        requests on cwiki, to find download links the first listing already
        held.
        """
        if key not in self._files:
            self._files[key] = list(
                self._results(
                    f"{self._base}{CONTENT}/{key}/child/attachment", {"expand": "version"}
                )
            )
        return self._files[key]

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
            headers=self._headers({"Accept": "application/json"}),
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

    @classmethod
    def from_config(
        cls, config, *, workspace: Path, credential: object | None = None
    ) -> ConfluenceConnector:
        """Build from a `sources.yaml` entry (the entry-point contract).

        The credential arrives as an argument, resolved by `dossier.config`, the
        only package that reads the environment (R1.8).
        """
        url = config.options.get("url")
        query = config.options.get("query")
        if not url or not query:
            # Loading has already refused a confluence source missing either
            # (R1.10). Checked again because a connector is built from whatever
            # config it is handed, and one built by hand never went through the
            # loader.
            raise ValueError(
                f"source {config.id!r} has type 'confluence' and needs both `url` and `query`."
            )
        return cls(
            base_url=url,
            query=query,
            token=getattr(credential, "value", None),
            user=getattr(credential, "user", None),
            export=config.options.get("export"),
        )


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


def _exported(key: str) -> str | None:
    """The page whose PDF export `key` addresses, or `None` if it addresses something else.

    A page's key is its id and a file's is `<page id>/<filename>`, so
    `81920114.pdf` can only be the export.
    """
    if "/" not in key and key.endswith(EXPORT_SUFFIX):
        return key.removesuffix(EXPORT_SUFFIX)
    return None


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


# The entry point resolves to `ConfluenceConnector.from_config`, and a bound
# method reads its attributes from the function beneath it, so this is where the
# registry finds the declaration (R1.10), as it does for Jira.
ConfluenceConnector.from_config.__func__.keys = ConfluenceKeys
