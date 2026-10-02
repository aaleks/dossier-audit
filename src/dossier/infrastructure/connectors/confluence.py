"""The Confluence connector: pages from a CQL query, and the files they carry (spec 001).

Reads, and only reads (R1.1). Every route here is a `GET`: as in the Jira
connector, there is no method on this class that creates, edits, moves or marks
anything, so a write is not guarded against -- it is absent.

Read against Confluence Data Center 9.2 (spec 001, "A Confluence page").

`httpx` is imported inside the functions that use it. A `dossier convert` that
never builds this connector should not pay for the import.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, model_validator

from dossier.domain.confluence import (
    commented_version,
    export_version,
    included_pages,
    including_version,
)
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

# A page's comments, with `comments: true` (R1.23): every one, replies included,
# rendered as the page is, with who wrote it and when. Only this route returns a
# reply. Expanded on the page, `children.comment` is the top-level comments, 25
# at most, as a Data Center 9.2.21 answered on 2026-09-27.
COMMENTS = "/child/comment"
COMMENT_EXPAND = "body.export_view,version,history,ancestors"

# The pages that draw another page's text into them (R1.26), which CQL knows by
# their macros. Which page each one names is written only in the storage format,
# so these pages, and the ones they name, are asked for with it.
INCLUDES = 'macro in (include, "excerpt-include")'
STORAGE_EXPAND = "version,space,body.storage"

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

# How many page ids, or titles, one `id in (...)`, `container in (...)` or
# `title in (...)` search names: which pages whose files changed the query
# matches (R1.22), which comments listed pages carry (R1.24), and which pages
# are included (R1.26). A cap on the URL's length, not on anything CQL says.
IDS_PER_SEARCH = 50

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
    each page's PDF export beside it (R1.19), and `comments: true` holds each
    page with its comments (R1.23).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    query: str
    token_env: str = ""
    user_env: str = ""
    export: Export | None = None
    comments: bool = False

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
        comments: bool = False,
        transport: Any | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._query = query
        self._export = export
        self._comments = comments
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
        if since is None:
            yield from self._marked([*self._pages(cql)], since=None)
            return

        window = _modified_since(since)
        pages = [*self._pages(f"{cql} AND {window}")]

        # A page's `lastmodified` does not move when a file on it does, nor a
        # comment, so the search above leaves out a page whose only change is a
        # file uploaded again (R1.22) or a comment added (R1.25). What changed
        # names its page; the query then decides which of those are in scope.
        # It is never applied to what changed: `label = runbook` matches pages,
        # not their files.
        touched = sorted(self._containers_of_changed(window) - {p.key for p in pages})
        for ids in _batches(touched):
            pages += self._pages(f"{cql} AND id in ({', '.join(ids)})")
        yield from self._marked(pages, since=since)

    def _marked(self, pages: list[ItemRef], *, since: datetime | None) -> Iterator[ItemRef]:
        """`pages`, each marked by what it includes (R1.26), then by its comments (R1.24).

        Under a window, a page whose included text changed is listed too: an
        edit to an included page leaves the including one out of the window's
        search (R1.27). It is in scope, since the query found it including.
        """
        included = self._included()
        if since is not None:
            floor = server_zone_floor(since)
            listed = {page.key for page in pages}
            pages = pages + [
                drawn.ref
                for key, drawn in sorted(included.items())
                if key not in listed and drawn.changed is not None and drawn.changed >= floor
            ]
        yield from self._commented([self._including(page, included) for page in pages])

    def _including(self, page: ItemRef, included: Mapping[str, _Drawn]) -> ItemRef:
        """`page`, marked by what it draws in, when it draws anything in (R1.26).

        `_versions` keeps this marker, and the export's is made from it: the PDF
        draws the included text as the page does (R1.19).
        """
        if page.key not in included:
            return page
        self._versions[page.key] = including_version(
            page.remote_version, included[page.key].markers
        )
        return page.model_copy(update={"remote_version": self._versions[page.key]})

    def _included(self) -> dict[str, _Drawn]:
        """What each of the query's pages that includes another draws in, by page id (R1.26).

        Asked at every sync, windowed or not: an edit to an included page leaves
        the including one where it was. Inclusions are followed through the
        included pages, since Confluence draws those too, and each page is
        counted once. An include naming no page counts as `missing:…`.
        """
        including = [
            *self._results(
                f"{self._base}{SEARCH}",
                {
                    "cql": f"({self._query}) AND type = page AND {INCLUDES}",
                    "expand": STORAGE_EXPAND,
                },
            )
        ]
        names = {str(page["id"]): _names(page) for page in including}
        found: dict[tuple[str, str], dict | None] = {}
        wanted = {name for named in names.values() for name in named}
        while wanted:
            answered = self._named(sorted(wanted))
            for name in wanted:
                found[name] = answered.get(name)
            for page in answered.values():
                names.setdefault(str(page["id"]), _names(page))
            wanted = {name for page in answered.values() for name in names[str(page["id"])]}
            wanted -= found.keys()
        drawn: dict[str, _Drawn] = {}
        for page in including:
            key = str(page["id"])
            markers, changed = _drawn_in(key, names, found)
            ref = ItemRef(key=key, remote_version=_version_of(page), updated_at=_when(page))
            drawn[key] = _Drawn(ref=ref, markers=markers, changed=changed)
        return drawn

    def _named(self, names: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
        """The pages `names` names, each `(space, title)`, asked for by space and title."""
        found: dict[tuple[str, str], dict] = {}
        spaces = sorted({space for space, _ in names})
        for space in spaces:
            titles = [title for named_space, title in names if named_space == space]
            for batch in _batches(titles):
                for page in self._results(
                    f"{self._base}{SEARCH}",
                    {
                        "cql": f"type = page AND space = {_quoted(space)} AND title in "
                        f"({', '.join(_quoted(title) for title in batch)})",
                        "expand": STORAGE_EXPAND,
                    },
                ):
                    found[(space, str(page.get("title")))] = page
        return found

    def _commented(self, pages: list[ItemRef]) -> Iterator[ItemRef]:
        """`pages`, each marked by its comments too when `comments: true` asks (R1.24).

        A comment leaves its page at its version, so the page's marker says what
        its comments are. Which comments the pages carry is asked once for every
        `IDS_PER_SEARCH` pages, not once a page. What `_versions` keeps is the
        marker before this, which the export's is made from (R1.19): the PDF
        does not draw comments, as a Data Center 9.2.21's did not on 2026-09-27.
        """
        if not self._comments:
            yield from pages
            return
        comments: dict[str, list[str | None]] = {}
        for ids in _batches([page.key for page in pages]):
            for comment in self._results(
                f"{self._base}{SEARCH}",
                {
                    "cql": f"type = comment AND container in ({', '.join(ids)})",
                    "expand": "version,container",
                },
            ):
                page = str((comment.get("container") or {}).get("id"))
                comments.setdefault(page, []).append(_file_version_of(comment))
        for page in pages:
            yield page.model_copy(
                update={
                    "remote_version": commented_version(
                        page.remote_version, comments.get(page.key, [])
                    )
                }
            )

    def _pages(self, cql: str) -> Iterator[ItemRef]:
        """The pages one search matches, each keyed by its id and marked by its version."""
        for page in self._results(f"{self._base}{SEARCH}", {"cql": cql, "expand": "version"}):
            # The id, never the title: a rename would otherwise be a
            # tombstone and a new item rather than an edit (R1.16, R2.7).
            key = str(page["id"])
            self._versions[key] = _version_of(page)
            yield ItemRef(key=key, remote_version=self._versions[key], updated_at=_when(page))

    def _containers_of_changed(self, window: str) -> set[str]:
        """The ids of what carries each file changed inside `window` (R1.22), and
        each comment with `comments: true` (R1.25).

        Data Center names a result's container only when asked to expand it. A
        file on a blog post names the post, which `type = page` then leaves out.
        A reply's container is the page, not the comment it answers.
        """
        kinds = "type in (attachment, comment)" if self._comments else "type = attachment"
        return {
            str(container["id"])
            for changed in self._results(
                f"{self._base}{SEARCH}",
                {"cql": f"{kinds} AND {window}", "expand": "container"},
            )
            if (container := changed.get("container")) and container.get("id")
        }

    def fetch(self, key: str) -> RawItem:
        """The payload at `key`: a page, or a file one of them carries.

        Returned byte for byte, as received (R1.43). A page is its JSON rendered
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
                payload=self._with_comments(page, response.content),
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

    def _with_comments(self, page: str, sent: bytes) -> bytes:
        """Page `page` as sent, and with `comments: true` its comments beside it (R1.23).

        Each answer is written into the payload as Confluence sent it, byte for
        byte, rather than parsed and written out again (R1.43): the payload is
        `{"page":<the page>,"comments":[<each answer>]}`.
        """
        if not self._comments:
            return sent
        answers = self._answers(
            f"{self._base}{CONTENT}/{page}{COMMENTS}",
            {"depth": "all", "expand": COMMENT_EXPAND},
        )
        return b'{"page":' + sent + b',"comments":[' + b",".join(answers) + b"]}"

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
        """Every result a paged answer holds, asked for `PAGE_SIZE` at a time."""
        for sent in self._answers(url, params):
            yield from json.loads(sent).get("results") or []

    def _answers(self, url: str, params: Mapping[str, object]) -> Iterator[bytes]:
        """Each answer to a paged question, as sent, asked for `PAGE_SIZE` at a time.

        Search, a page's files and its comments page the same way: by `start`
        and `limit`, until an answer names no `next` (R1.15, R1.18, R1.23). An
        empty page of results ends it too, so a server that always names one
        cannot loop.
        """
        start = 0
        while True:
            response = self._get(url, params={**params, "start": start, "limit": PAGE_SIZE})
            yield response.content

            answer = response.json()
            results = answer.get("results") or []
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
            comments=config.options.get("comments") is True,
        )


def _version_of(page: Mapping[str, Any]) -> str | None:
    """A page's marker: Confluence's version number, written `v37` (R1.16).

    `None` when the answer carries no number, never a fetch time: a made-up
    marker makes R2.1 skip a page that did change (R1.5).
    """
    number = (page.get("version") or {}).get("number")
    return f"v{number}" if number is not None else None


def _batches(ids: list[str]) -> Iterator[list[str]]:
    """`ids`, `IDS_PER_SEARCH` at a time, for an `id in (…)` or `container in (…)` search."""
    for start in range(0, len(ids), IDS_PER_SEARCH):
        yield ids[start : start + IDS_PER_SEARCH]


def _names(page: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The `(space, title)` of each page `page` includes, read from its storage (R1.26)."""
    storage = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
    space = str((page.get("space") or {}).get("key") or "")
    return included_pages(storage, space=space)


class _Drawn(NamedTuple):
    """A page that includes others: as a listing would list it, what it draws in
    (R1.26), and when the latest of that last changed (R1.27)."""

    ref: ItemRef
    markers: list[str | None]
    changed: datetime | None


def _drawn_in(
    start: str,
    names: Mapping[str, list[tuple[str, str]]],
    found: Mapping[tuple[str, str], Mapping[str, Any] | None],
) -> tuple[list[str | None], datetime | None]:
    """The markers of everything page `start` draws in, through other pages too
    (R1.26), and when the latest of them last changed (R1.27).

    Each page once, and never `start` itself: two pages including each other
    end here rather than going round.
    """
    markers: list[str | None] = []
    changed: datetime | None = None
    seen: set[tuple[str, str]] = set()
    counted = {start}
    todo = list(names.get(start, []))
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        page = found.get(name)
        if page is None:
            markers.append(f"missing:{name[0]}/{name[1]}")
            continue
        key = str(page["id"])
        if key in counted:
            continue
        counted.add(key)
        markers.append(_file_version_of(page))
        when = _when(page)
        if when is not None and (changed is None or when > changed):
            changed = when
        todo.extend(names.get(key, []))
    return markers, changed


def _quoted(text: str) -> str:
    """`text` as a CQL string: in double quotes, with `\\` and `"` escaped."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _file_version_of(attachment: Mapping[str, Any]) -> str | None:
    """A file's marker: its attachment id and version, `81920301:v2` (R1.18).

    Both, because each alone misses a case. Uploading again under the same name
    keeps the id and raises the version; deleting and uploading again makes a
    new id and starts the version at 1 again. A comment's is written the same
    way, `81920501:v2`, for R1.24's digest.
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
