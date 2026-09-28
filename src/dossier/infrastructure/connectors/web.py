"""The web connector: a website, read from its sitemap or its links (spec 001, R1.29 - R1.43).

One connector for every website. A site is a `url` in
`sources.yaml`, never code: the pages under it are what its sitemap names
(R1.29), each keyed by its URL relative to `url` (R1.30) and marked by its
`<lastmod>` (R1.31). A site with no sitemap is crawled when its source says
`crawl:`: the pages are those its links reach within `url` (R1.37), and a crawl
that cannot finish lists nothing (R1.38). What a sitemap says, which URLs a
source covers, which links a crawl follows and how far apart its requests go
are decided in `dossier.domain.web`; this module asks.

A page built in the browser is drawn by one when its source says
`render: browser` (R1.40). The page is asked here, as every page is, and what
the site sent is handed to a headless Chromium (`browser`), which runs its
scripts. Every request they make comes back here to be answered, sent or
refused (R1.41), so the site is asked by a browser only as it is asked by this
module.

It asks politely. A site that answers `429` is asked nothing more that sync
(R1.35), and requests are spaced by the longer of the source's `delay:` and the
site's `Crawl-delay` (R1.36).

Reads, and only reads (R1.1). Every request is a `GET`, and there is no other
method here to make one.

`httpx` is imported inside the functions that use it. A `dossier convert` that
never builds this connector should not pay for the import.
"""

from __future__ import annotations

import codecs
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from dossier.domain.conversion import reported_media_type
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.web import (
    ASKED_ONCE,
    Frontier,
    Listed,
    SitemapPage,
    browser_asks,
    in_scope,
    lastmod_time,
    links,
    listing,
    prefix,
    robots_answer,
    same_host,
    sitemap,
    spacing,
)
from dossier.infrastructure.connectors import browser as browsers
from dossier.infrastructure.connectors.browser import (
    Answer,
    Asked,
    Browser,
    Decision,
    DrawFailed,
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

# The one media type a crawl reads links from (R1.37 row 7), and a browser
# draws (R1.40 row 6).
PAGE = "text/html"

# What an answer handed to a browser does not carry on: httpx has already
# undone the encoding, and the length is the browser's to count.
NOT_PASSED_ON = frozenset(
    {"content-encoding", "content-length", "transfer-encoding", "connection"}
)


class WebRequestFailed(RuntimeError):
    """A site could not be reached, or did not answer as a page, sitemap or robots.txt should.

    The message names the URL and what went wrong.
    """


class WebRedirectRefused(WebRequestFailed):
    """A redirect led somewhere the request may not follow (R1.34).

    A page a sitemap named fails with it. A link a crawl followed is simply not
    a page of this source (R1.37 row 9).
    """


class _Refused(Exception):
    """A redirect `_get` will not follow, raised from inside httpx and caught around it."""


class WebKeys(BaseModel):
    """The keys a `web` source takes beyond the shared ones (R1.10).

    `url` is the prefix the source covers, read as a directory whether or not it
    ends in `/` (R1.30 row 5). `sitemap` is where its pages are listed from;
    absent, it is the host's own `/sitemap.xml`. `crawl` lists them by their
    links instead, asking at most that many URLs (R1.37). `render: browser`
    draws each HTML page in a headless browser (R1.40). `delay` is the seconds
    between its requests; absent, none but what the site's `Crawl-delay` asks
    (R1.36).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    sitemap: str = ""
    # How many URLs, so a whole number and at least one; strict, so `true` is
    # refused rather than read as `1` by a person who meant "crawl it" (R1.39).
    crawl: Annotated[StrictInt, Field(ge=1)] | None = None
    # One way to draw a page, named, so that a second is a new value and not a
    # `true` that meant the first (R1.42 row 1).
    render: Literal["browser"] | None = None
    # A wait, so no less than 0, and finite: `.inf` in YAML would be a sync
    # that never asks its second request (R1.36 row 7).
    delay: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def _listed_one_way(self) -> WebKeys:
        if self.crawl is not None and self.sitemap:
            raise ValueError(
                "`crawl` and `sitemap` are two ways to list one source; "
                "a web source says one of them (R1.39)"
            )
        return self

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
    """Every page a site's sitemap names under one URL prefix, or that its links reach."""

    # A sitemap names every page each time it is read, and a crawl reaches
    # every page or fails; `since` narrows neither. Every listing is complete,
    # and a page gone from it is tombstoned (R1.11, R1.29 row 4, R1.38).
    lists_everything = True

    def __init__(
        self,
        *,
        url: str,
        sitemap_url: str | None = None,
        crawl: int | None = None,
        render: Literal["browser"] | None = None,
        delay: float | None = None,
        transport: Any | None = None,
        browser: Callable[[], AbstractContextManager[Browser]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._scope = prefix(url)
        parts = urlsplit(self._scope)
        self._site = f"{parts.scheme}://{parts.netloc}"
        self._sitemap = sitemap_url or f"{self._site}/sitemap.xml"
        # The most URLs a crawl asks, or `None` for a source listed by its
        # sitemap (R1.37, R1.39).
        self._crawl = crawl
        # What a crawl was answered, by key, so that `fetch` asks nothing: a
        # crawl has already downloaded every page to list it (R1.37 row 2).
        self._bodies: dict[str, tuple[bytes, str]] = {}
        # Whether an HTML page is drawn by a browser, and what opens one: a
        # headless Chromium, unless a test hands in another (R1.40).
        self._render = render == "browser"
        self._browser = browser or (
            lambda: browsers.Chromium(user_agent=USER_AGENT, timeout_seconds=TIMEOUT_SECONDS)
        )
        # A script or stylesheet of the site's, as it was answered, so that a
        # second page loading it asks nothing (R1.41 row 5).
        self._assets: dict[str, Answer] = {}
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
        """Every page the sitemap names under `url`, or its links reach, sorted by key.

        `since` is accepted and ignored: a sitemap is read whole, a crawl goes
        everywhere, and returning more than asked is always allowed (R1.4). The
        listing is settled before its first ref is yielded, so a sitemap that
        fails, a crawl that cannot finish, or two URLs that claim one key, stop
        the listing before sync has seen any of it (R1.29, R1.38).
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
        """The page at `key`, byte for byte, labelled as its server said (R1.32, R1.43).

        As its server sent it, or with `render: browser` and an HTML page, as a
        browser drew it (R1.40).

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
            named = (
                f"a crawl of {self._scope} reached" if self._crawl else f"{self._sitemap} names"
            )
            raise WebRequestFailed(f"{key!r} is not a page {named} under {self._scope}")
        if key in self._bodies:
            payload, media_type = self._bodies[key]
            return RawItem(key=key, payload=payload, media_type=media_type, remote_version=None)

        response = self._get(
            listed.url,
            may_follow=lambda target: in_scope(target, self._scope),
            refused=f"outside {self._scope}, which this source covers (R1.34)",
        )
        if not response.is_success:
            raise WebRequestFailed(
                f"GET {listed.url} answered {response.status_code} {response.reason_phrase}"
            )
        media_type = reported_media_type(None, response.headers.get("content-type"))
        payload = response.content
        if self._render and media_type == PAGE:
            with self._opened() as browser:
                _, payload = self._drawn(browser, response)
        return RawItem(
            key=key, payload=payload, media_type=media_type, remote_version=listed.lastmod
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        """Nothing: a web page carries no files (R1.32 row 3).

        A file it links to is an item of its own when the sitemap names it, and
        otherwise is not held.
        """
        return iter(())

    def _listing(self) -> dict[str, Listed]:
        """Every page in scope, by key: from every sitemap reachable from the first,
        or from every link reachable from `url` when the source crawls."""
        robots = self._robots_txt()
        allowed = lambda url: robots.can_fetch(url, USER_AGENT)  # noqa: E731
        try:
            if self._crawl is not None:
                pages, disallowed = self._crawled(allowed)
            else:
                listed = listing(self._sitemap_pages(), self._scope, allowed=allowed)
                pages, disallowed = listed.pages, listed.disallowed
        except ValueError as error:
            raise WebRequestFailed(str(error)) from None
        self._pages, self._disallowed = pages, disallowed
        return pages

    def _crawled(
        self, allowed: Callable[[str], bool]
    ) -> tuple[dict[str, Listed], dict[str, str]]:
        """Every page the links from `url` reach within it, and what robots.txt kept out.

        Each URL is asked once (R1.37). A page is kept by the address it was answered
        at, with the bytes it was answered with, so `fetch` asks nothing. A link
        that is not a page -- a `4xx` other than `429`, or a redirect out of
        `url` -- is passed over. Anything else that is not a page fails the
        whole crawl, and so does `url` not being one: what a crawl did not reach
        it cannot say is gone (R1.38).
        """
        frontier = Frontier(self._scope, limit=self._crawl or 0, allowed=allowed)
        found: list[SitemapPage] = []
        bodies: dict[str, tuple[bytes, str]] = {}
        start = True
        with self._opened() if self._render else nullcontext() as browser:
            while (url := frontier.next()) is not None:
                first, start = start, False
                page = self._crawl_one(url, first=first, browser=browser)
                if page is None:
                    continue
                answered, payload, media_type, html = page
                if answered in bodies:
                    continue
                frontier.answered(answered)
                found.append(SitemapPage(loc=answered, lastmod=None))
                bodies[answered] = (payload, media_type)
                if html is not None:
                    frontier.add(links(html, answered))
        listed = listing(found, self._scope, allowed=lambda _: True)
        self._bodies = {key: bodies[page.url] for key, page in listed.pages.items()}
        return listed.pages, frontier.disallowed

    def _crawl_one(self, url: str, *, first: bool, browser: Browser | None):
        """One URL of a crawl: where it was answered, its bytes, its media type and its
        HTML to read links from, or `None` for a link that is not a page (R1.37, R1.38)."""
        try:
            response = self._get(
                url,
                may_follow=lambda target: in_scope(target, self._scope),
                refused=f"outside {self._scope}, which this source covers (R1.34)",
            )
        except WebRedirectRefused:
            if first:
                raise
            return None
        if not response.is_success:
            if first or not response.is_client_error:
                raise WebRequestFailed(
                    f"GET {url} answered {response.status_code} "
                    f"{response.reason_phrase}; a crawl that cannot read a page "
                    "cannot say which pages it did not reach, so nothing is "
                    "listed (R1.38)"
                )
            return None
        media_type = reported_media_type(None, response.headers.get("content-type"))
        if media_type != PAGE:
            return str(response.url), response.content, media_type, None
        if browser is None:
            return str(response.url), response.content, media_type, response.text
        html, payload = self._drawn(browser, response)
        return str(response.url), payload, media_type, html

    @contextmanager
    def _opened(self) -> Iterator[Browser]:
        """A browser, for one crawl or one page (R1.40).

        One that cannot be started fails what needed it -- the page, or the
        crawl -- naming why, as any request that cannot be made does (R1.42).
        """
        try:
            with self._browser() as browser:
                yield browser
        except DrawFailed as error:
            raise WebRequestFailed(str(error)) from None

    def _drawn(self, browser: Browser, response) -> tuple[str, bytes]:
        """The page `response` answered, as `browser` draws it: its HTML, and its bytes.

        The browser is handed what the site sent, at the URL it was answered at,
        and asks for nothing without `_decision` answering first (R1.40, R1.41).
        The bytes are the drawn page in UTF-8 behind a byte-order mark, which a
        browser and `html-markdown` read before any charset the page declares
        (R8.32, R1.43): the `<meta charset>` it still carries may not be the one
        the browser read it in.
        """
        url = str(response.url)
        page = Answer(
            status=response.status_code,
            headers=_passed_on(response.headers),
            body=response.content,
        )
        robots = self._robots_txt()
        drawn = [False]

        def decide(asked: Asked) -> Decision:
            return self._decision(
                asked,
                url=url,
                page=page,
                drawn=drawn,
                allowed=lambda target: robots.can_fetch(target, USER_AGENT),
            )

        refused_before = self._refused
        try:
            drawn_html = browser.draw(url, decide)
        except DrawFailed as error:
            raise WebRequestFailed(str(error)) from None
        if self._refused is not None and refused_before is None:
            raise WebRequestFailed(
                f"{self._refused} answered 429 Too Many Requests while {url} was being "
                f"drawn, so the page is not held; {self._site} is asked nothing more this "
                "sync (R1.35). A `delay:` on the source asks it more slowly (R1.36)"
            )
        return drawn_html, codecs.BOM_UTF8 + drawn_html.encode("utf-8")

    def _decision(
        self,
        asked: Asked,
        *,
        url: str,
        page: Answer,
        drawn: list[bool],
        allowed: Callable[[str], bool],
    ) -> Decision:
        """What becomes of one request a page being drawn makes (R1.41).

        Which is the domain's to decide. Answering is this module's: the page
        itself from what the site already sent, and a request to the site through
        `_get`, where `robots.txt`, `delay:` and a `429` hold as for any page. A
        failure there refuses the request, and the page is drawn without it.
        """
        verdict = browser_asks(
            url=asked.url,
            method=asked.method,
            kind=asked.kind,
            navigation=asked.navigation,
            main_frame=asked.main_frame,
            page=url,
            drawn=drawn[0],
            allowed=allowed,
        )
        if verdict == "page":
            drawn[0] = True
            return page
        if verdict != "site":
            return verdict
        if asked.url in self._assets:
            return self._assets[asked.url]
        try:
            response = self._get(
                asked.url, may_follow=lambda _target: True, refused="which is not followed"
            )
        except WebRequestFailed:
            return "refuse"
        answer = Answer(
            status=response.status_code,
            headers=_passed_on(response.headers),
            body=response.content,
        )
        if asked.kind in ASKED_ONCE and response.is_success:
            self._assets[asked.url] = answer
        return answer

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
                raise WebRedirectRefused(
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
        render = config.options.get("render")
        if render == "browser" and not browsers.installed():
            # Refused here, before a request: every page of the source would
            # otherwise fail one at a time, each for the same missing package.
            raise ValueError(
                f"source {config.id!r} says `render: browser`, and Playwright is not "
                f"installed. Install the extra `{browsers.EXTRA}`, then "
                f"`{browsers.INSTALL_CHROMIUM}` (R1.42)."
            )
        return cls(
            url=url,
            sitemap_url=config.options.get("sitemap") or None,
            crawl=config.options.get("crawl"),
            render=render,
            delay=config.options.get("delay"),
        )


def _passed_on(headers) -> dict[str, str]:
    """A response's headers, as a browser handed its body is to see them (R1.40)."""
    return {name: value for name, value in headers.items() if name.lower() not in NOT_PASSED_ON}


# The entry point resolves to `WebConnector.from_config`, and a bound method
# reads its attributes from the function beneath it -- so this is where the
# registry finds the declaration (R1.10), with no change to the entry point.
WebConnector.from_config.__func__.keys = WebKeys
