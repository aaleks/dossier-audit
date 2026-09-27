"""The web connector: a website, read from its sitemap (spec 001, R1.29 - R1.36).

One connector for every website. A site is a `url` in
`sources.yaml`, never code: the pages under it are what its sitemap names
(R1.29), each keyed by its URL relative to `url` (R1.30) and marked by its
`<lastmod>` (R1.31). What a sitemap says, which URLs a source covers, and how
far apart its requests go are decided in `dossier.domain.web`; this module asks.

It asks politely. A site that answers `429` is asked nothing more that sync
(R1.35), and requests are spaced by the longer of the source's `delay:` and the
site's `Crawl-delay` (R1.36).

Reads, and only reads (R1.1). Every request is a `GET`, and there is no other
method here to make one.

`httpx` is imported inside the functions that use it. A `dossier convert` that
never builds this connector should not pay for the import.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dossier.domain.conversion import reported_media_type
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.web import (
    Listed,
    in_scope,
    lastmod_time,
    listing,
    prefix,
    robots_answer,
    same_host,
    sitemap,
    spacing,
)

# Who `dossier` says it is, to the server and to its `robots.txt` (R1.33).
USER_AGENT = "dossier"

# How many redirects a request follows before it is refused (R1.34 row 2).
MAX_REDIRECTS = 5

# Generous, and bounded, as the Jira connector's is: a server that never
# answers must end the sync rather than hang it.
TIMEOUT_SECONDS = 60.0

# What a site answers when it is asked too often (R1.35).
TOO_MANY_REQUESTS = 429


class WebRequestFailed(RuntimeError):
    """A site could not be reached, or did not answer as a page, sitemap or robots.txt should.

    The message names the URL and what went wrong.
    """


class _Refused(Exception):
    """A redirect `_get` will not follow, raised from inside httpx and caught around it."""


class WebKeys(BaseModel):
    """The keys a `web` source takes beyond the shared ones (R1.10).

    `url` is the prefix the source covers, read as a directory whether or not it
    ends in `/` (R1.30 row 5). `sitemap` is where its pages are listed from;
    absent, it is the host's own `/sitemap.xml`. `delay` is the seconds between
    its requests; absent, none but what the site's `Crawl-delay` asks (R1.36).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    sitemap: str = ""
    # A wait, so no less than 0, and finite: `.inf` in YAML would be a sync
    # that never asks its second request (R1.36 row 7).
    delay: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None

    @field_validator("url", "sitemap")
    @classmethod
    def _an_http_url(cls, value: str, info) -> str:
        # Refused at load time rather than at the first request: `docs.example.org/ops`
        # without a scheme would otherwise be a path on no host at all (R1.10).
        if info.field_name == "sitemap" and not value:
            return value
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"{value!r} is not an http(s) URL naming a host")
        return value.strip()


class WebConnector:
    """Every page a site's sitemap names under one URL prefix."""

    # A sitemap names every page each time it is read, and `since` narrows
    # nothing: every listing is complete, and a page gone from it is
    # tombstoned (R1.11, R1.29 row 4).
    lists_everything = True

    def __init__(
        self,
        *,
        url: str,
        sitemap_url: str | None = None,
        delay: float | None = None,
        transport: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._scope = prefix(url)
        parts = urlsplit(self._scope)
        self._site = f"{parts.scheme}://{parts.netloc}"
        self._sitemap = sitemap_url or f"{self._site}/sitemap.xml"
        self._transport = transport
        self._robots: Any | None = None
        # The wait and the clock are handed in, so a test about waiting five
        # seconds takes none (R1.36).
        self._delay = delay
        self._sleep = sleep
        self._clock = clock
        # When the last request to the site was sent, by `clock`.
        self._last_sent: float | None = None
        # The URL the site answered `429`, after which it is asked nothing
        # more. A connector is built for each sync, so this lasts one (R1.35).
        self._refused: str | None = None
        # Each key's URL and marker, as the last listing gave them. `fetch`
        # needs the URL, and a key alone cannot say whether `runbooks/index`
        # was `…/runbooks/` or `…/runbooks/index` (R1.30).
        self._pages: dict[str, Listed] | None = None
        # What robots.txt kept out of that listing, so that a fetch of one says
        # why rather than that it was never there (R1.33 row 2).
        self._disallowed: dict[str, str] = {}

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        """Every page the sitemap names under `url`, sorted by key (R1.29).

        `since` is accepted and ignored: a sitemap is read whole, and returning
        more than asked is always allowed (R1.4). The listing is settled before
        its first ref is yielded, so a sitemap that fails, or two URLs that
        claim one key, stop the listing before sync has seen any of it.
        """
        pages = self._listing()
        for key in sorted(pages):
            listed = pages[key]
            yield ItemRef(
                key=key,
                remote_version=listed.lastmod,
                updated_at=lastmod_time(listed.lastmod),
            )

    def fetch(self, key: str) -> RawItem:
        """The page at `key`, byte for byte, labelled as its server said (R1.2, R1.32).

        A key this connector has not listed yet is looked up by listing: sync
        may ask again for a key whose fetch failed without listing it first
        (R2.23).
        """
        pages = self._pages
        if pages is None or key not in pages:
            pages = self._listing()
        if key in self._disallowed:
            raise WebRequestFailed(
                f"{self._disallowed[key]} is disallowed for {USER_AGENT!r} by "
                f"{self._site}/robots.txt, and is not fetched (R1.33)"
            )
        listed = pages.get(key)
        if listed is None:
            raise WebRequestFailed(
                f"{key!r} is not a page {self._sitemap} names under {self._scope}"
            )

        response = self._get(
            listed.url,
            may_follow=lambda target: in_scope(target, self._scope),
            refused=f"outside {self._scope}, which this source covers (R1.34)",
        )
        if not response.is_success:
            raise WebRequestFailed(
                f"GET {listed.url} answered {response.status_code} {response.reason_phrase}"
            )
        return RawItem(
            key=key,
            payload=response.content,
            media_type=reported_media_type(None, response.headers.get("content-type")),
            remote_version=listed.lastmod,
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        """Nothing: a web page carries no files (R1.32 row 3).

        A file it links to is an item of its own when the sitemap names it, and
        otherwise is not held.
        """
        return iter(())

    def _listing(self) -> dict[str, Listed]:
        """Every page in scope, by key, from every sitemap reachable from the first."""
        robots = self._robots_txt()
        try:
            listed = listing(
                self._sitemap_pages(),
                self._scope,
                allowed=lambda url: robots.can_fetch(url, USER_AGENT),
            )
        except ValueError as error:
            raise WebRequestFailed(str(error)) from None
        self._pages, self._disallowed = listed.pages, listed.disallowed
        return listed.pages

    def _sitemap_pages(self):
        """The pages of the sitemap and of every sitemap it indexes on the same host (R1.29)."""
        queue, seen = [self._sitemap], {self._sitemap}
        while queue:
            url = queue.pop(0)
            response = self._get(
                url,
                may_follow=lambda target, asked=url: same_host(target, asked),
                refused="on another host than the sitemap",
            )
            if not response.is_success:
                raise WebRequestFailed(
                    f"GET {url} answered {response.status_code} {response.reason_phrase}; "
                    "a web source is listed from its sitemap, and nothing is tombstoned "
                    "without one (R1.29)"
                )
            try:
                read = sitemap(response.content)
            except ValueError as error:
                raise WebRequestFailed(f"{url}: {error}") from None
            yield from read.pages
            for child in read.children:
                if child not in seen and same_host(child, self._sitemap):
                    seen.add(child)
                    queue.append(child)

    def _robots_txt(self):
        """The host's `robots.txt`, read once for this connector (R1.33).

        Absent (`4xx`) allows everything, as RFC 9309 says. Unreadable (`5xx`,
        or no answer) fails the listing: RFC 9309 reads it as disallowing
        everything, which here would tombstone every page held.
        """
        if self._robots is not None:
            return self._robots
        from protego import Protego

        url = f"{self._site}/robots.txt"
        response = self._get(
            url,
            may_follow=lambda target: same_host(target, url),
            refused="on another host than the site",
        )
        answer = robots_answer(response.status_code)
        if answer == "read":
            self._robots = Protego.parse(response.text)
        elif answer == "allow_all":
            self._robots = Protego.parse("")
        else:
            raise WebRequestFailed(
                f"GET {url} answered {response.status_code} {response.reason_phrase}; "
                "an unreadable robots.txt disallows everything, so nothing is listed (R1.33)"
            )
        return self._robots

    def _get(self, url: str, *, may_follow: Callable[[str], bool], refused: str):
        """One read, following redirects that `may_follow` allows, at most `MAX_REDIRECTS`.

        The only verb this connector has. httpx follows the redirects; a
        request hook sees each hop before it is sent, so a page that sends
        `dossier` to a login form or another site is refused without asking
        either (R1.34), and every hop waits its turn (R1.36).

        A `429` fails here, and so does every request after it, unsent: a site
        that says it is asked too often is not asked again this sync (R1.35).
        """
        import httpx

        if self._refused is not None:
            raise WebRequestFailed(
                f"GET {url} not sent: {self._refused} was answered 429 Too Many "
                "Requests, and a site that says so is asked nothing more this sync "
                "(R1.35). It is asked again at the next sync; a `delay:` on the "
                "source asks it more slowly (R1.36)"
            )

        def vet(request: httpx.Request) -> None:
            target = str(request.url)
            if target != url and not may_follow(target):
                raise _Refused(target)
            self._pace()

        with httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            transport=self._transport,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            event_hooks={"request": [vet]},
        ) as http:
            try:
                response = http.get(url)
            except _Refused as refusal:
                raise WebRequestFailed(
                    f"GET {url} redirected to {refusal}, {refused}"
                ) from None
            except httpx.TooManyRedirects:
                raise WebRequestFailed(
                    f"GET {url} redirected more than {MAX_REDIRECTS} times (R1.34)"
                ) from None
            except httpx.HTTPError as error:
                raise WebRequestFailed(f"GET {url} failed: {error}") from None
        if response.status_code == TOO_MANY_REQUESTS:
            self._refused = url
            raise WebRequestFailed(
                f"GET {url} answered 429 Too Many Requests; {self._site} is asked "
                "nothing more this sync (R1.35). A `delay:` on the source asks it "
                "more slowly (R1.36)"
            )
        return response

    def _pace(self) -> None:
        """Wait until the request about to be sent is far enough from the last (R1.36).

        How far is the domain's decision. The `Crawl-delay` is known once
        `robots.txt` has been read, which is the first request; before that, only
        `delay:` applies, and to the first request nothing does.
        """
        crawl_delay = self._robots.crawl_delay(USER_AGENT) if self._robots is not None else None
        gap = spacing(self._delay, crawl_delay)
        now = self._clock()
        if self._last_sent is not None and gap > 0:
            wait = gap - (now - self._last_sent)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_sent = now

    @classmethod
    def from_config(
        cls, config, *, workspace: Path, credential: object | None = None
    ) -> WebConnector:
        """Build from a `sources.yaml` entry (the entry-point contract).

        `credential` is accepted and unused: every request is anonymous (spec
        001, open question 8). Taking the argument keeps every connector built
        the same way (R1.7).
        """
        url = config.options.get("url")
        if not url:
            # Loading has already refused a web source with no `url` (R1.10).
            # Checked again because a connector is built from whatever config it
            # is handed, and one built by hand never went through the loader.
            raise ValueError(f"source {config.id!r} has type 'web' and needs a `url`.")
        return cls(
            url=url,
            sitemap_url=config.options.get("sitemap") or None,
            delay=config.options.get("delay"),
        )


# The entry point resolves to `WebConnector.from_config`, and a bound method
# reads its attributes from the function beneath it -- so this is where the
# registry finds the declaration (R1.10), with no change to the entry point.
WebConnector.from_config.__func__.keys = WebKeys
