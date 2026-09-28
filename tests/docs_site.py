"""`vendor-docs`, the website of `specs/_fixtures.md`, served with no socket.

An `httpx.MockTransport` playing `https://docs.example.org`: a sitemap, a
`robots.txt` and the pages they name, each changeable per test. Every request
is recorded, so a test can say what was asked as well as what came back.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

SITE = "https://docs.example.org"
URL = f"{SITE}/ops/"
SITEMAP = f"{SITE}/sitemap.xml"
ROBOTS = f"{SITE}/robots.txt"

HTML = "text/html; charset=utf-8"

# The fixtures' robots.txt, where a rule needs `drafts/` kept out (R1.33).
ROBOTS_TXT = "User-agent: *\nDisallow: /ops/drafts/\n"

# The fixtures table, as a sitemap names it: URL and `<lastmod>`.
PAGES: dict[str, str | None] = {
    f"{SITE}/ops/": "2026-08-05",
    f"{SITE}/ops/escalation": "2026-08-05T16:02:00+00:00",
    f"{SITE}/ops/runbooks/dns-failover.html": None,
    f"{SITE}/ops/escalation-matrix.pdf": "2026-08-04",
    f"{SITE}/blog/release-notes": "2026-08-06",
}


def urlset(pages: dict[str, str | None]) -> bytes:
    """A sitemap naming `pages`, with a `<lastmod>` where one is given."""
    entries = "".join(
        f"<url><loc>{loc}</loc>"
        + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "")
        + "</url>"
        for loc, lastmod in pages.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</urlset>"
    ).encode()


def sitemapindex(children: list[str]) -> bytes:
    """A sitemap index naming `children`."""
    entries = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in children)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</sitemapindex>"
    ).encode()


# The fixtures' links, where a rule needs a crawl (R1.37 - R1.39): the `href`s
# each page holds, written relative to it as a site writes them.
LINKS: dict[str, list[str]] = {
    f"{SITE}/ops/": ["escalation", "runbooks/dns-failover.html", "escalation-matrix.pdf"],
    f"{SITE}/ops/escalation": ["./", "drafts/escalation-v2", "/blog/release-notes"],
    f"{SITE}/ops/runbooks/dns-failover.html": ["../escalation"],
}


def page_body(url: str, links: list[str] | None = None) -> bytes:
    """A small page naming `url`, linking what `LINKS` says it does unless told otherwise."""
    hrefs = LINKS.get(url, []) if links is None else links
    anchors = "".join(f'<a href="{href}">{href}</a>' for href in hrefs)
    return f"<html><body><h1>{url}</h1>{anchors}</body></html>".encode()


@dataclass
class DocsSite:
    """The site. `responses` overrides what any URL answers; everything else is defaulted.

    By default the sitemap names `PAGES`, `robots.txt` is `404`, and each page
    answers `200` with a small HTML body linking what `links` says -- the PDF
    with PDF bytes.
    """

    pages: dict[str, str | None] = field(default_factory=lambda: dict(PAGES))
    responses: dict[str, httpx.Response] = field(default_factory=dict)
    links: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in LINKS.items()}
    )
    asked: list[httpx.Request] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.asked.append(request)
            url = str(request.url)
            if url in self.responses:
                answer = self.responses[url]
                return httpx.Response(
                    answer.status_code, headers=answer.headers, content=answer.content
                )
            if url == SITEMAP:
                return httpx.Response(200, content=urlset(self.pages))
            if url == ROBOTS:
                return httpx.Response(404)
            if url.endswith(".pdf"):
                return httpx.Response(
                    200, headers={"Content-Type": "application/pdf"}, content=b"%PDF-1.7\n"
                )
            if url in self.pages:
                return httpx.Response(
                    200,
                    headers={"Content-Type": HTML},
                    content=page_body(url, self.links.get(url, [])),
                )
            return httpx.Response(404)

        return httpx.MockTransport(handle)

    def urls_asked(self) -> list[str]:
        return [str(request.url) for request in self.asked]
