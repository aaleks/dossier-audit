"""What a web source decides without asking the network (spec 001, R1.29 - R1.39).

Which URLs a source's `url` covers, what each is keyed as, what a sitemap says,
which links a crawl follows and when it must stop, and how far apart its
requests go. Each is a pure function of strings, bytes and numbers, so the
connector asks and this decides: the connector holds the requests, and nothing
here knows there was one.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
import zlib
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

# What a directory's key ends in. A key is also a file name under `runs/`
# (R0.11), and `runbooks/` is not one.
DIRECTORY_INDEX = "index"

# The first bytes of every gzip stream. A sitemap served compressed is read
# compressed, whatever it is named and whatever header it came with (R1.29 row 3).
GZIP_MAGIC = b"\x1f\x8b"

# The most a sitemap may hold uncompressed, as the sitemaps.org protocol sets it.
# A compressed sitemap is inflated no further than this, so a small file that
# would inflate without end is refused rather than read.
SITEMAP_LIMIT = 50 * 1024 * 1024


@dataclass(frozen=True)
class SitemapPage:
    """One `<url>` a sitemap names: where it is, and its `<lastmod>` as written."""

    loc: str
    lastmod: str | None


@dataclass(frozen=True)
class Sitemap:
    """What one sitemap document says: the pages it names, or the sitemaps it indexes."""

    pages: tuple[SitemapPage, ...]
    children: tuple[str, ...]


def prefix(url: str) -> str:
    """The source's `url` read as a directory: `…/ops` and `…/ops/` are one scope.

    Without the slash, `…/ops` would be a prefix of `…/opsx/guide` (R1.30 row 5).
    """
    url = urldefrag(url.strip()).url
    return url if url.endswith("/") else f"{url}/"


def in_scope(url: str, scope: str) -> bool:
    """Whether `url` is a page under `scope`, a `prefix` (R1.29).

    The scheme and host must match, and the host case-insensitively as DNS reads
    it; the path must lie under the prefix's. A URL carrying a query is out: a
    query is how a site serves one page many ways, and none of them is its
    address (R1.29 row 5). The fragment is dropped first, since it is not part of
    an address at all (R1.30 row 6).
    """
    url = urldefrag(url.strip()).url
    page, base = urlsplit(url), urlsplit(scope)
    if page.query:
        return False
    if page.scheme.lower() != base.scheme.lower() or not _same_host(page.netloc, base.netloc):
        return False
    return (page.path or "/").startswith(base.path or "/") or f"{page.path}/" == base.path


def page_key(url: str, scope: str) -> str:
    """A page's key: its URL relative to `scope`, with `index` for a directory (R1.30).

    The path is kept as the sitemap spells it, percent-escapes included.
    Decoding it would be a second decision about what the site meant, and two
    spellings of one character would then be one key for two URLs.
    """
    url = urldefrag(url.strip()).url
    path, base = urlsplit(url).path or "/", urlsplit(scope).path or "/"
    if f"{path}/" == base:
        # `url: …/ops` names the directory whose listing is `…/ops/`, and a
        # sitemap may spell the page either way.
        return DIRECTORY_INDEX
    relative = path[len(base) :]
    if relative == "" or relative.endswith("/"):
        return f"{relative}{DIRECTORY_INDEX}"
    return relative


def same_host(url: str, other: str) -> bool:
    """Whether two URLs name one host, whatever their scheme (R1.29 row 7, R1.34 row 4).

    Where a sitemap index may point, and where a sitemap or `robots.txt` may
    redirect. The scheme is not compared: `http` answered with its `https` form
    is the same site moving, not another site.
    """
    return _same_host(urlsplit(url).netloc, urlsplit(other).netloc)


@dataclass(frozen=True)
class Listed:
    """A page in a listing: the URL it is fetched from, and its marker (R1.31)."""

    url: str
    lastmod: str | None


@dataclass(frozen=True)
class Listing:
    """A web source's pages by key, and what `robots.txt` kept out of them (R1.29, R1.33)."""

    pages: dict[str, Listed]
    disallowed: dict[str, str]


def listing(
    pages: Iterable[SitemapPage], scope: str, *, allowed: Callable[[str], bool]
) -> Listing:
    """The pages under `scope`, keyed, with the ones `allowed` refuses set aside.

    A URL named twice is one page, and the first `<lastmod>` given for it
    stands. Two different URLs that come to one key are refused: one key cannot
    hold two pages, and holding either would silently lose the other (R1.30
    row 7). A fragment is dropped before either comparison (R1.30 row 6).
    """
    kept: dict[str, Listed] = {}
    disallowed: dict[str, str] = {}
    for page in pages:
        if not in_scope(page.loc, scope):
            continue
        url = urldefrag(page.loc.strip()).url
        key = page_key(url, scope)
        if not allowed(url):
            disallowed[key] = url
            continue
        held = kept.get(key)
        if held is None:
            kept[key] = Listed(url=url, lastmod=page.lastmod)
        elif held.url != url:
            raise ValueError(
                f"{held.url} and {url} are both keyed {key!r} under {scope}; "
                "one key cannot hold two pages (R1.30)"
            )
    return Listing(pages=kept, disallowed=disallowed)


def robots_answer(status: int) -> Literal["read", "allow_all", "refuse"]:
    """What a `robots.txt` answered with `status` means for a listing (R1.33).

    Read when it was served. Absent -- any `4xx` -- allows everything, as RFC
    9309 says. Anything else is unreadable, which RFC 9309 reads as disallowing
    everything; a listing that obeyed would be empty, and an empty complete
    listing tombstones every page held, so the listing is refused instead
    (R1.33 row 5).
    """
    if 200 <= status < 300:
        return "read"
    if 400 <= status < 500:
        return "allow_all"
    return "refuse"


def sitemap(payload: bytes) -> Sitemap:
    """The pages or child sitemaps one sitemap document names (R1.29, R1.31).

    Elements are matched by local name, so a sitemap that declares the
    `sitemaps.org` namespace and one that forgets to are read alike. A `<loc>`
    that is empty is not a page. A `<lastmod>` is kept exactly as written, and
    whether it reads as a time is `lastmod_time`'s question, not this one's.

    Raises `ValueError` for anything that is not a sitemap: a listing built
    from a page of HTML would be empty, and an empty complete listing tombstones
    everything the source holds (R1.29 row 6).
    """
    if payload.startswith(GZIP_MAGIC):
        payload = _gunzipped(payload)
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ValueError(f"not a sitemap: {error}") from None

    kind = _local(root.tag)
    if kind == "urlset":
        pages = []
        for entry in root:
            if _local(entry.tag) != "url":
                continue
            loc = _text(entry, "loc")
            if loc:
                pages.append(SitemapPage(loc=loc, lastmod=_text(entry, "lastmod")))
        return Sitemap(pages=tuple(pages), children=())
    if kind == "sitemapindex":
        children = [
            loc
            for entry in root
            if _local(entry.tag) == "sitemap" and (loc := _text(entry, "loc"))
        ]
        return Sitemap(pages=(), children=tuple(children))
    raise ValueError(f"not a sitemap: the document is <{kind}>, not <urlset> or <sitemapindex>")


def links(html: str, url: str) -> tuple[str, ...]:
    """Where a page's links go: every `<a href>`, absolute, in the order written (R1.37).

    Each is read against the page's first `<base href>`, as a browser reads it,
    or failing one against `url`, the address the page was answered at. The
    fragment is dropped, since it is not part of an address (R1.30 row 6). Which
    of them a crawl follows is `Frontier`'s question, not this one's.
    """
    reader = _Links()
    reader.feed(html)
    reader.close()
    base = urljoin(url, reader.base) if reader.base is not None else url
    found: dict[str, None] = {}
    for href in reader.hrefs:
        found.setdefault(urldefrag(urljoin(base, href.strip())).url, None)
    return tuple(found)


class Frontier:
    """Which URL a crawl asks next, and when it may not ask another (R1.37, R1.38).

    It starts at the source's `scope`, a `prefix`. It follows each link that
    lies under it (`in_scope`), keeps back the ones `allowed` refuses -- by key,
    in `disallowed`, as a sitemap's listing does (R1.33) -- and hands each URL
    out once, in the order the links were found. A URL is one address whatever
    case its scheme and host are written in.

    It hands out at most `limit` URLs. Asked for one more while any is left, it
    raises `ValueError`: a crawl that stops short is not a complete listing, and
    a complete listing tombstones what it does not name (R1.38).
    """

    def __init__(self, scope: str, *, limit: int, allowed: Callable[[str], bool]) -> None:
        self._scope = scope
        self._limit = limit
        self._allowed = allowed
        self._queue: deque[str] = deque()
        self._seen: set[str] = set()
        self._answered: set[str] = set()
        self._asked = 0
        self.disallowed: dict[str, str] = {}
        self.add([scope])
        if not self._queue:
            raise ValueError(
                f"{scope} is disallowed for this source by robots.txt, and a crawl "
                "that may not start reaches nothing (R1.33, R1.38)"
            )

    def add(self, urls: Iterable[str]) -> None:
        """Queue the links under the scope that have not been seen."""
        for url in urls:
            address = _address(url)
            if address in self._seen or not in_scope(address, self._scope):
                continue
            self._seen.add(address)
            if not self._allowed(address):
                self.disallowed[page_key(address, self._scope)] = address
                continue
            self._queue.append(address)

    def answered(self, url: str) -> None:
        """A page was answered at `url`, which is therefore not asked again."""
        address = _address(url)
        self._seen.add(address)
        self._answered.add(address)

    def next(self) -> str | None:
        """The next URL to ask, or `None` once the crawl has reached everything."""
        while self._queue:
            url = self._queue.popleft()
            if url in self._answered:
                continue
            if self._asked >= self._limit:
                raise ValueError(
                    f"the crawl has asked {self._limit} URLs, as many as `crawl:` "
                    f"allows, and {url} is still to ask. A crawl that stops short "
                    "would tombstone every page it did not reach, so nothing is "
                    "listed; raise `crawl:` to list this source (R1.38)"
                )
            self._asked += 1
            return url
        return None


# What a page loads that draws no text: the note is the page's text, and an
# image is its alt text (R1.41 row 1, R8.22). Named as Playwright names them.
UNDRAWN = frozenset({"image", "media", "font"})

# What every page of a site loads alike, and is asked for once a sync however
# many pages load it (R1.41 row 5).
ASKED_ONCE = frozenset({"script", "stylesheet"})


def browser_asks(
    *,
    url: str,
    method: str,
    kind: str,
    navigation: bool,
    main_frame: bool,
    page: str,
    drawn: bool,
    allowed: Callable[[str], bool],
) -> Literal["page", "site", "send", "refuse", "stay"]:
    """What becomes of one request a page being drawn at `page` makes (R1.40, R1.41).

    - `page`: the page's own document, the first time it is asked for. The
      connector answers it with what the site already sent, so the browser
      never asks for it again (R1.40 row 2).
    - `stay`: any other move of the page's own frame -- a script sending the
      browser to a login form. It is not followed, and the page is held as drawn.
    - `refuse`: another frame's page; anything but `GET`, which could write
      (R1.1); an image, video, audio or font; a request to the site that
      `robots.txt` disallows (R1.33).
    - `site`: a request to the page's own host, asked as its pages are asked.
    - `send`: a request to another host, which is the page's own, and which the
      browser sends.

    `drawn` is whether the page's own document has been answered already.
    """
    if navigation and main_frame:
        return "page" if _address(url) == _address(page) and not drawn else "stay"
    if navigation or method.upper() != "GET" or kind in UNDRAWN:
        return "refuse"
    if not same_host(url, page):
        return "send"
    return "site" if allowed(url) else "refuse"


def spacing(delay: float | None, crawl_delay: float | None) -> float:
    """How far apart, in seconds, a web source starts its requests to its site (R1.36).

    The longer of the source's `delay:` and the `Crawl-delay` its site's
    `robots.txt` gives `dossier`: the site's pace is a floor a source may raise
    and never lower. With neither, `0`, and requests go back to back.
    """
    return float(max(delay or 0, crawl_delay or 0))


def lastmod_time(lastmod: str | None) -> datetime | None:
    """A `<lastmod>` as a time, or `None` when it does not read as one (R1.31).

    The W3C forms a sitemap uses: a date alone is midnight UTC that day, and a
    time without an offset is taken as UTC rather than as this machine's zone
    (R0.4). `updated_at` is advisory, so an unreadable one is absent, never a
    guess; the marker itself is the string, and is never parsed (R1.31 row 5).
    """
    if not lastmod:
        return None
    text = lastmod.strip()
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), datetime.min.time(), tzinfo=UTC)
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _gunzipped(payload: bytes) -> bytes:
    """A gzip stream inflated, to at most `SITEMAP_LIMIT` bytes."""
    inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    try:
        inflated = inflater.decompress(payload, SITEMAP_LIMIT)
    except zlib.error as error:
        raise ValueError(f"not a sitemap: {error}") from None
    if inflater.unconsumed_tail:
        raise ValueError(f"not a sitemap: it inflates past {SITEMAP_LIMIT} bytes")
    return inflated


def _same_host(first: str, second: str) -> bool:
    return first.lower() == second.lower()


def _address(url: str) -> str:
    """`url` without its fragment, and with its scheme and host as DNS reads them."""
    parts = urlsplit(urldefrag(url.strip()).url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


class _Links(HTMLParser):
    """The `href` of every `<a>` in a page, and of its first `<base>`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.base: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if href is None:
            return
        if tag == "a":
            self.hrefs.append(href)
        elif tag == "base" and self.base is None:
            self.base = href

    handle_startendtag = handle_starttag


def _local(tag: str) -> str:
    """`{http://www.sitemaps.org/schemas/sitemap/0.9}url` as `url`."""
    return tag.rpartition("}")[2]


def _text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _local(child.tag) == name:
            text = (child.text or "").strip()
            return text or None
    return None
