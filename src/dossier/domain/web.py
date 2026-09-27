"""What a web source decides without asking the network (spec 001, R1.23 - R1.25).

Which URLs a source's `url` covers, what each is keyed as, and what a sitemap
says. Each is a pure function of strings and bytes, so the connector asks and
this decides: the connector holds the requests, and nothing here knows there
was one.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import urldefrag, urlsplit

# What a directory's key ends in. A key is also a file name under `runs/`
# (R0.11), and `runbooks/` is not one.
DIRECTORY_INDEX = "index"

# The first bytes of every gzip stream. A sitemap served compressed is read
# compressed, whatever it is named and whatever header it came with (R1.23 row 3).
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

    Without the slash, `…/ops` would be a prefix of `…/opsx/guide` (R1.24 row 5).
    """
    url = urldefrag(url.strip()).url
    return url if url.endswith("/") else f"{url}/"


def in_scope(url: str, scope: str) -> bool:
    """Whether `url` is a page under `scope`, a `prefix` (R1.23).

    The scheme and host must match, and the host case-insensitively as DNS reads
    it; the path must lie under the prefix's. A URL carrying a query is out: a
    query is how a site serves one page many ways, and none of them is its
    address (R1.23 row 5). The fragment is dropped first, since it is not part of
    an address at all (R1.24 row 6).
    """
    url = urldefrag(url.strip()).url
    page, base = urlsplit(url), urlsplit(scope)
    if page.query:
        return False
    if page.scheme.lower() != base.scheme.lower() or not _same_host(page.netloc, base.netloc):
        return False
    return (page.path or "/").startswith(base.path or "/") or f"{page.path}/" == base.path


def page_key(url: str, scope: str) -> str:
    """A page's key: its URL relative to `scope`, with `index` for a directory (R1.24).

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
    """Whether two URLs name one host, whatever their scheme (R1.23 row 7, R1.28 row 4).

    Where a sitemap index may point, and where a sitemap or `robots.txt` may
    redirect. The scheme is not compared: `http` answered with its `https` form
    is the same site moving, not another site.
    """
    return _same_host(urlsplit(url).netloc, urlsplit(other).netloc)


@dataclass(frozen=True)
class Listed:
    """A page in a listing: the URL it is fetched from, and its marker (R1.25)."""

    url: str
    lastmod: str | None


@dataclass(frozen=True)
class Listing:
    """A web source's pages by key, and what `robots.txt` kept out of them (R1.23, R1.27)."""

    pages: dict[str, Listed]
    disallowed: dict[str, str]


def listing(
    pages: Iterable[SitemapPage], scope: str, *, allowed: Callable[[str], bool]
) -> Listing:
    """The pages under `scope`, keyed, with the ones `allowed` refuses set aside.

    A URL named twice is one page, and the first `<lastmod>` given for it
    stands. Two different URLs that come to one key are refused: one key cannot
    hold two pages, and holding either would silently lose the other (R1.24
    row 7). A fragment is dropped before either comparison (R1.24 row 6).
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
                "one key cannot hold two pages (R1.24)"
            )
    return Listing(pages=kept, disallowed=disallowed)


def robots_answer(status: int) -> Literal["read", "allow_all", "refuse"]:
    """What a `robots.txt` answered with `status` means for a listing (R1.27).

    Read when it was served. Absent -- any `4xx` -- allows everything, as RFC
    9309 says. Anything else is unreadable, which RFC 9309 reads as disallowing
    everything; a listing that obeyed would be empty, and an empty complete
    listing tombstones every page held, so the listing is refused instead
    (R1.27 row 5).
    """
    if 200 <= status < 300:
        return "read"
    if 400 <= status < 500:
        return "allow_all"
    return "refuse"


def sitemap(payload: bytes) -> Sitemap:
    """The pages or child sitemaps one sitemap document names (R1.23, R1.25).

    Elements are matched by local name, so a sitemap that declares the
    `sitemaps.org` namespace and one that forgets to are read alike. A `<loc>`
    that is empty is not a page. A `<lastmod>` is kept exactly as written, and
    whether it reads as a time is `lastmod_time`'s question, not this one's.

    Raises `ValueError` for anything that is not a sitemap: a listing built
    from a page of HTML would be empty, and an empty complete listing tombstones
    everything the source holds (R1.23 row 6).
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


def lastmod_time(lastmod: str | None) -> datetime | None:
    """A `<lastmod>` as a time, or `None` when it does not read as one (R1.25).

    The W3C forms a sitemap uses: a date alone is midnight UTC that day, and a
    time without an offset is taken as UTC rather than as this machine's zone
    (R0.4). `updated_at` is advisory, so an unreadable one is absent, never a
    guess; the marker itself is the string, and is never parsed (R1.25 row 5).
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


def _local(tag: str) -> str:
    """`{http://www.sitemaps.org/schemas/sitemap/0.9}url` as `url`."""
    return tag.rpartition("}")[2]


def _text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _local(child.tag) == name:
            text = (child.text or "").strip()
            return text or None
    return None
