"""`vendor-docs`, the documentation site of `specs/_fixtures.md`, served with no socket.

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


def page_body(url: str) -> bytes:
    return f"<html><body><h1>{url}</h1></body></html>".encode()


@dataclass
class DocsSite:
    """The site. `responses` overrides what any URL answers; everything else is defaulted.

    By default the sitemap names `PAGES`, `robots.txt` is `404`, and each page
    answers `200` with a small HTML body -- the PDF with PDF bytes.
    """

    pages: dict[str, str | None] = field(default_factory=lambda: dict(PAGES))
    responses: dict[str, httpx.Response] = field(default_factory=dict)
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
                    200, headers={"Content-Type": HTML}, content=page_body(url)
                )
            return httpx.Response(404)

        return httpx.MockTransport(handle)

    def urls_asked(self) -> list[str]:
        return [str(request.url) for request in self.asked]
