# 001 — Source connectors

**Status:** Partially implemented
**Rules:** R1.1 – R1.39

## Purpose

Define the single interface every source type implements, so that adding a new
source system requires no change to the ledger, the store, the cache or any
pipeline.

Connectors are left of the hash boundary, with the model clients and the tracker
(R0.10). Everything a
connector does is therefore assumed to be unrepeatable, and everything after it
is assumed not to be.

## Interface

A connector implements exactly three operations, and declares one fact about
the first of them.

```python
class Connector(Protocol):
    lists_everything: bool
    """Whether every listing this connector returns is complete -- that is,
    whether `list` ignores `since`. A folder has no change times and always
    returns everything; Jira narrows its query. Sync computes tombstones
    against a listing it knows to be complete, and this is how a connector
    that never narrows says so (R1.11, R2.21)."""

    def list(self, since: datetime | None) -> Iterator[ItemRef]:
        """Every item currently in scope. When `since` is given, the connector
        MAY restrict the result to items changed at or after it. Returning more
        than asked for is always allowed; returning less is not."""

    def fetch(self, key: str) -> RawItem:
        """The full payload of one addressable thing: an item, or an
        attachment one of them carries."""

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        """Files attached to the item, each independently addressable."""
```

```python
class ItemRef(BaseModel):
    key: str                      # stable within the source, e.g. "INC-4821"
    remote_version: str | None    # server-side version marker, if any
    updated_at: datetime | None

class RawItem(BaseModel):
    key: str
    payload: bytes                # exactly as received, unmodified
    media_type: str
    remote_version: str | None

class AttachmentRef(BaseModel):
    key: str                      # the attachment's own address, e.g. "INC-4821/report.pdf"
    item_key: str                 # the item carrying it, e.g. "INC-4821"
    remote_version: str | None    # the attachment's marker, not its item's
```

`lists_everything` is a fact about the source type, not about one call. A Jira
listing asked for with `since=None` is complete, but the connector still says
`False`: whether a particular call was complete is sync's to work out from the
`since` it passed (R2.21), and the declaration only adds the case sync cannot
see -- a connector that would have returned everything whatever it was asked.
A connector that declares nothing is refused when it is built for a source
(R1.11): silence here is exactly the gap that left a deleted file `active`.

An attachment is addressed exactly as an item is, and `fetch` takes either key:
`attachments()` says which files an item carries, and the `key` on each ref is
what fetches those bytes. That is what R1.6 means by independently addressable,
and it is why there is no fourth operation — a second way to fetch bytes at an
address would be one question asked twice, and the two answers could come to
disagree about R1.2.

The `Connector` protocol and its value objects live in `dossier.domain.ports`.
They are pure types; the implementations live in
`dossier.infrastructure.connectors`.

## Registration

Connectors are discovered through the `dossier.connectors` entry point group.
A new source type is a package that declares one; it is never added to a match
statement inside `dossier`.

```toml
[project.entry-points."dossier.connectors"]
jira = "dossier_jira:JiraConnector"
```

A connector also declares the keys its sources take (R1.10). The keys every
source has -- `id`, `type`, `fields`, `convert`, `watermark_overlap` -- are the
core's. Everything else belongs to one type, and only its connector knows it.

## Connector types in scope

- **folder** — a local directory. `remote_version` is always `None`; change
  detection falls back to payload hashing (spec 002).
- **jira** — scoped by a JQL query. Issue fields as JSON, attachments separate.
  Its keys: `url` and `query`; `token_env` naming the credential's variable and
  `user_env` naming the user's, which together decide the auth scheme (R1.12);
  and `deployment`, `datacenter` or `cloud`, which decides the listing route
  (R1.13).
- **confluence** — scoped by a CQL query. A page as Confluence renders it for
  export, as JSON; the files it carries separate; and, where the server allows
  it, its PDF export beside it. Its keys: `url` and `query`; `token_env` and
  `user_env`, read as a Jira source reads them (R1.21); and `export: pdf`, which
  asks for the PDF (R1.19). Read against Data Center.
- **web** — scoped by a URL prefix, and listed from the site's sitemap or, when
  the source asks, by following its links. A page as the server sent it,
  labelled with the media type the server stated. Its keys: `url`, the prefix;
  `sitemap`, where the listing is read from; `crawl`, the most URLs a crawl
  asks, in place of a sitemap (R1.37); and `delay`, the seconds between
  requests (R1.36). One connector for every website: a site is configuration,
  never code.

## A Confluence page

**What is held.** A page is fetched as Confluence renders it for export --
`GET /rest/api/content/{id}?expand=body.export_view,version,space` -- stored as
the bytes Confluence sent (R1.2), and labelled
`application/vnd.dossier.confluence-page+json` (R1.17), the type
`confluence-page-markdown` claims (R8.19). The rendered body, and not the storage
format: storage holds `<ac:structured-macro>` elements that only Confluence knows
how to draw, and a converter reading it would be rebuilding Confluence's renderer
one macro at a time. `export_view` is the page a reader sees, with absolute URLs
and no script.

This replaces the PDF-only export this section used to name. Its reason -- the
embedded images carry meaning the storage format loses -- still holds, and is met
twice: every image a page shows is a file the page carries, fetched and converted
as its own document (R1.18), and a source with `export: pdf` holds each page's
PDF export beside it (R1.19). What the PDF-only design did not survive was a real
server. The export is a user-interface action, not a REST route, and
administrators refuse it: `cwiki.apache.org` (Data Center 9.2.21) and
`confluence.ecmwf.int` both answer it `403` to an anonymous reader while serving
the same page's JSON. A connector that could hold a page only as a PDF would hold
nothing from either.

**What is listed.** The pages the source's CQL `query` matches, and only pages
(R1.15). A CQL query is the Confluence counterpart of a Jira source's JQL, and
reaches everything a space-and-label scope does -- `space = OPS AND label =
procedure` -- and a page tree as well (`ancestor = 81920100`). A page's key is its
id, `81920114`, and never its title (R1.16). A title changes when a page is
renamed, and a key that changes turns an edit into a tombstone and a new item
(R2.7). The note carries the title.

**The PDF export, when the server allows it.** `export: pdf` is the workspace
saying that this server exports. The connector asks
`GET /spaces/flyingpdf/pdfpageexport.action?pageId=81920114` with
`X-Atlassian-Token: no-check`, the header Confluence requires before it will run
an action that a cross-site request could trigger. The action answers `302` to a
file under `/download/export/`, which is fetched in the same session. This was
checked against `confluence.atlassian.com` (Data Center), which allows anonymous
export: without the header it answers `403`, and two exports of one version
differ only in the random `/ID` in the PDF's trailer. A server that refuses is
reported rather than worked around (R1.20). A PDF that went missing without a
word would look exactly like a page that has none.

The export is keyed `<page id>.pdf`, and the page carries it, as it carries an
attachment. It is tombstoned with the page, and when `export:` is taken away
(R2.6 row 3). Its marker moves when the page's marker moves, and when the marker
of any file the page carries moves (R1.19). An image uploaded again in place
leaves the page at its version, and changes the PDF, which draws the image.

Asking for an export makes the server render a PDF and keep it for a while in its
own export directory. That costs the server work, but it changes nothing a person
reads, and every request is still a `GET` (R1.1). It is why `export:` is absent
by default.

**Comments, when asked for.** `comments: true` holds a page with every comment
on it, footer and inline, replies included (R1.23). Only
`GET /rest/api/content/{id}/child/comment?depth=all` returns a reply: expanded on
the page, `children.comment` is the top-level comments, 25 at most. A comment is
content of its own, so adding, editing or removing one leaves the page at its
version and its `lastmodified` where it was. That was read against a Data Center
9.2.21 in Docker on 2026-09-27. So the page's marker also says what its comments
are (R1.24), and a windowed listing also asks which comments changed (R1.25). It
is off by default, because it costs a search for every 50 pages listed.

**Text a page includes from another.** `include` and `excerpt-include` draw
another page's text into a page. On the same server, `Escalation contacts` was
edited to version 2. The page including it stayed at version 1, and out of a
windowed search, while its `export_view` changed. So the including page's marker
says what it includes (R1.26), and a windowed listing lists it when what it
includes changed (R1.27). Confluence knows which pages use either macro (CQL's
`macro` field). Which page each one names is written only in the storage format,
as `<ri:page ri:content-title="…" ri:space-key="…"/>`.

**Two consequences, accepted.** The table-of-contents macro is drawn with a class
name that holds the time it was rendered (`div.rbtoc1790332347793`), and a PDF
export carries a random `/ID`. So two fetches of one version are not the same
bytes. A fetch is stored as sent (R1.2), so re-fetching an unchanged version
stores a new snapshot. That happens only when `fields:` changes (R2.3), because
an unchanged marker is otherwise never fetched (R2.1). The converter drops the
table of contents (R8.20). The note is therefore the same bytes, and a stage
reading it is served from cache.

The export converts to `markdown` by default (R8.10). A list under `convert:`
applies to every document a source holds, so `convert: [markdown, page_images]`
asks `page_images` of the page JSON too, and nothing claims that pair (R8.24).
`convert: {application/pdf: [markdown, page_images]}` asks it of the export
alone (R8.26).

**Existing options considered**, before writing the connector:

| Option | Checked | Covers | Missing |
|---|---|---|---|
| [`atlassian-python-api`](https://github.com/atlassian-api/atlassian-python-api) 5.0.5 | Apache-2.0, released 2026-09-14, active | CQL search, pages, attachments, and the PDF export through the same action and header used here | It is built on `requests`, a second HTTP client beside `httpx`, which `MockTransport` does not reach. Its Confluence class has hundreds of methods that create, update, move and delete. R1.1's strongest form -- the write is absent from the class, not guarded against -- could not hold |
| [`confluence-markdown-exporter`](https://pypi.org/project/confluence-markdown-exporter/) 5.4.0 | MIT, released 2026-08-17 | Fetches pages and writes them as markdown files, through `atlassian-python-api` and `markdownify` | It is an application, not a library. It writes converted markdown to disk, so no payload is kept as sent (R1.2). Fetching and converting are one step, where `dossier` keys them separately (R5.4) |
| A connector over `httpx`, as Jira's is | -- | Five `GET` routes, and the authorization Jira's connector already decides | The whole delta, about the size of the Jira connector |

**Chosen: `httpx`**, as the Jira connector uses. What turns the body into
markdown is spec 008's decision (R8.20).

## A web source

**What it is for.** A website, read as documents. Every website is the same
thing to a reader: pages at URLs. So one connector reads all of them, and a new
site is a `sources.yaml` entry. Documentation sites -- MkDocs, Sphinx,
Docusaurus, Read the Docs -- are the case it was written against, and the
example below is one; nothing in the connector is specific to them.

What it reads well is a site that publishes a sitemap, serves its pages as
HTML from the server, and lets an anonymous reader in. A site with no sitemap
is crawled when its source asks (R1.37). A site that builds its pages in the
browser with JavaScript is held as the empty shell the server sent (question
10), and one behind a login is question 8.

```yaml
- id: vendor-docs
  type: web
  url: https://docs.example.org/ops/
  # sitemap: https://docs.example.org/sitemap.xml   (the default: the host's own)
  # crawl: 200   (in place of a sitemap: follow links, asking at most 200 URLs)
  # delay: 2   (seconds between requests; the default: none)
```

**What is listed.** Every URL the sitemap names under `url`, and nothing else
(R1.29). A sitemap index is followed to the sitemaps it names, on the same host.
A sitemap served compressed is read compressed. `url` is a prefix of the whole
URL, scheme and host included, and is read as a directory whether or not it
ends in `/`: `…/ops` does not match `…/opsx/`. A URL carrying a query string is
left out, because a query is how a site serves one page many ways, and none of
them is the page's address.

The sitemap is the listing, unless the source asks for a crawl. A sitemap is what a site
publishes to say which pages it has; the generators behind nearly every
documentation site write one, and most content management systems do too. A crawl asks every page once just to find the
next, which is every page downloaded on every sync before anything is known to
have changed. So a crawl is something a source asks for (R1.37). It never
happens because a sitemap is missing: a sitemap that cannot be read still fails
the listing.

The listing is complete: `since` is ignored, `lists_everything` is `True`, and
a page gone from the sitemap is tombstoned (R1.11, R2.7). That is also why a
sitemap that cannot be read fails the listing, and is never an empty one. An
empty listing from a complete source tombstones everything held from it.

**Keys.** A page is keyed by its URL relative to `url` (R1.30):
`https://docs.example.org/ops/escalation` is `escalation`. A URL naming a
directory -- the prefix itself, or anything ending `/` -- has `index` appended,
because a key is also a file name under `runs/` (R0.11), and `runbooks/` is not
one. A fragment is not part of a page's address. The key is kept as the sitemap
spells it, percent-escapes included: decoding it would be a second decision
about what the site meant.

**Versions.** A page's marker is its `<lastmod>`, as the sitemap writes it
(R1.31). It costs nothing: the listing already holds it. A page with none has
no marker, and change detection falls back to its bytes (R1.5, R2.2). Some
generators stamp every page with the build time. That fetches more than
changed, and over-fetching is always allowed (R1.4). A generator that never
moves `<lastmod>` would leave a page stale, and the fix is `fields:` or a full
re-sync (R2.3), not a marker `dossier` invents.

**What is fetched.** `GET` of the page's URL, the bytes as sent (R1.2), labelled
with the media type the `Content-Type` header states (R1.32). A page is
`text/html`, and `html-markdown` converts it (R8.21). A PDF the sitemap lists is
`application/pdf`, and the PDF converters take it. A page carries nothing:
`attachments` is empty. An image the page draws is an item only if the sitemap
lists it, and otherwise it is its alt text in the note (R8.22).

**robots.txt.** A URL the host's `robots.txt` disallows for `dossier` is not
listed, and not fetched (R1.33). The file is read with
[`protego`](https://github.com/scrapy/protego), and `dossier` asks as the user
agent `dossier`. A `robots.txt` that is absent (any `4xx`) allows everything, as
RFC 9309 says. One that cannot be read (`5xx`, or no answer) fails the listing:
RFC 9309 reads it as disallowing everything, and here that would tombstone every
page held. A `429` is the exception among the `4xx`: it is not a file that is
absent, it is a site refusing to be asked, and nothing more is asked of it that
sync (R1.35). The sitemap goes unread, and the listing fails.

**Redirects.** A page may redirect within `url` -- `escalation` to
`escalation/` is common -- and the connector follows it, up to five times. A
redirect out of `url` fails that page and names both URLs (R1.34): a login page,
or another site, is not the page that was listed. The sitemap and `robots.txt`
follow redirects on their own host, which is how `http` becomes `https`.

**Politeness.** A site that answers `429 Too Many Requests` is asked nothing
more that sync (R1.35). The page it refused fails, and every page after it fails
without a request; sync owes them all to the next sync (R2.23). Before this, the
connector went on asking: `djangoproject.com`, read on 2026-09-27, refused 70 of
the 91 pages under `/foundation/` within seven seconds, and was sent all 70
requests after its first refusal.

Stopping is not enough on its own. A page with no `<lastmod>` is fetched on
every sync, in key order, so a site that allows twenty requests at a time spends
them on the same twenty pages every sync, and the rest are never held. What
lets such a site be read whole is asking it more slowly. Requests to a site
start at least the longer of two waits apart (R1.36): the source's `delay:`, in
seconds, and the `Crawl-delay` the site's `robots.txt` gives `dossier`. The
site's own pace is a floor a source may raise and never lower. With neither,
requests go back to back, as they always have: `docs.astral.sh/uv` lists 84
pages, and a first sync of them took 12 to 20 seconds in three runs.

A `429` is not retried within the sync, and no pace is guessed. A server that
says nothing about how long to wait -- `djangoproject.com` sent no
`Retry-After` -- leaves a retry to invent its interval, and a guessed interval
either wastes a sync or sends the refused requests again. The failure names
`delay:`, which is the remedy a person can apply.

**A site with no sitemap.** `www.python.org`, read on 2026-09-27, publishes no
sitemap and its `robots.txt` names none, so its listing failed on the `404`. A
source that says `crawl:` is listed by following links instead (R1.37).

- **What a crawl follows.** It starts at `url` and reads each page's links: the
  `href` of every `<a>`, read against the page's `<base>`, or failing one, the
  URL the page was answered at. It follows each link that lies under `url` as
  R1.29 reads it (fragment dropped, a URL with a query left out), and asks each
  URL once.
- **Keys.** A page is keyed as a sitemap's page would be, but by the URL it was
  answered at, after any redirect within `url` (R1.30). So when `escalation`
  redirects to `escalation/`, the two are one page.
- **Which pages are read for links.** Only HTML pages. A PDF that a page links
  to is listed, and its links are not read.

A crawl downloads every page just to list them, so the bytes are kept: `fetch`
returns what the crawl was answered, and a page is asked once a sync, not twice.
A crawled page has no marker (R1.31). It is compared by its bytes, and stored
again only when they changed (R2.2).

- **Links that are not pages.** A link answered `404`, or any `4xx` but `429`,
  is not a page, and neither is one that redirects out of `url` (a login form,
  another site). It is left out of the listing, and the crawl goes on: a site's
  broken links are not its pages.
- **`robots.txt`** is read as it is for a sitemap. A link it disallows is
  neither asked nor listed (R1.33), so that page's links are never read either.
- **`<meta name="robots">`** is not read. It tells a search engine what to
  index, and `dossier` indexes nothing; what may be asked is `robots.txt`'s to
  say.

A crawl lists everything it can reach, and sync tombstones any held page it did
not reach. So a crawl that cannot tell it has reached everything fails the
listing, and never returns what it has so far (R1.38). That happens when:

- `url` itself is not a page, or `robots.txt` disallows it;
- a page answers `5xx` or `429` (R1.35), or does not answer;
- a page redirects more than five times;
- the crawl would ask more URLs than `crawl:` allows.

That number is the source's to set, and there is no default. Only a site's
reader knows how many pages it has, and a crawl that stopped where a default
guessed would tombstone the rest. A source cannot say both `crawl:` and
`sitemap:` (R1.39).

**Existing options considered for crawling**, read from each package's source
on PyPI, 2026-09-28:

| Option | Covers | Missing |
|---|---|---|
| crawl4ai 0.9.4's `BFSDeepCrawlStrategy` | A breadth-first crawl, filters by URL pattern and domain, a page cap | It reads links only from pages that succeeded, and a failed page is one result among the others. So the crawl ends normally without the pages only that page linked to, and here they would be tombstoned. It fetches each level concurrently, up to twenty at once, and applies its cap in the order pages finish, so which pages a capped crawl lists depends on timing. It fetches through a browser or its own `aiohttp` client, never through the one request path that R1.33 to R1.36 govern. And taking it means taking crawl4ai (the table below) |
| Scrapy 2.19's `CrawlSpider` | Rules for which links to follow, `robots.txt`, depth and page limits | Its own engine (the table below) |
| Firecrawl's `crawl` | A site's pages, with or without a sitemap | Every page goes through a third party (the table below), and no site behind a firewall can be reached |

**Chosen: the connector's own requests, and the standard library's
`html.parser` for links.** What a crawl adds is a queue and a page's links.
Every rule a request follows (R1.33 to R1.36) is already in the one path the
connector sends through.

**Navigation.** A page is held as the site sent it, navigation, header and
footer included. `html-markdown` writes a page that declares one `<main>` as
that element, without the `<nav>` in it (R8.33), and so they are not in the note.
Leaving them out is a converter's decision, not a connector's: a snapshot is
what the site sent (R1.2), and deciding what is content is a key a converter's
version can move (R5.4).

**Not yet.** No credential: every request is anonymous (question 8).

**Existing options considered**, before writing the connector (PyPI, 2026-09-27):

| Option | Checked | Covers | Missing |
|---|---|---|---|
| [Scrapy](https://scrapy.org) 2.19 | BSD-3, released 2026-09-10, active | Crawling, sitemaps, robots.txt, throttling | A framework with its own engine and HTTP stack, run by its own loop. A connector is three calls another component makes (`list`, `fetch`, `attachments`), and Scrapy is not called that way. `httpx.MockTransport` does not reach it |
| [crawl4ai](https://github.com/unclecode/crawl4ai) 0.9.4 | Apache-2.0, released 2026-09-23 | Pages through a headless browser, as markdown for a model | A headless browser (Playwright, and Chromium to install) to read pages that are static HTML, and `litellm` in the install, used only by its model-driven extraction. R0.10 would not forbid it: the check is over `dossier`'s own imports, and this package is one of the three. What rules it out is weight, and that fetching and converting are one step, where `dossier` keys them separately (R5.4) |
| [Firecrawl](https://www.firecrawl.dev) (`firecrawl-py` 4.44.0) | MIT client, released 2026-09-20. A hosted service, or a server run yourself | Mapping a site's URLs with or without a sitemap, crawling, JavaScript rendering, a page as raw HTML or as markdown | Every page goes through a third party, with an API key and a charge per page. Its map gives no `<lastmod>`, so no page could be skipped as unchanged (R2.1): every sync would pay for every page. The client pulls `requests`, `httpx`, `aiohttp` and `websockets`. Worth another look for a site with no sitemap, or one that renders its pages in JavaScript (questions 7 and 10) |
| [trafilatura](https://github.com/adbar/trafilatura) 2.2 | Apache-2.0, released 2026-07-31 | Sitemaps, feeds, main-content extraction | Its downloader is `urllib3`, a second HTTP client. Its extraction is the heuristic spec 008 declined (R8.21) |
| [ultimate-sitemap-parser](https://github.com/GateNLP/ultimate-sitemap-parser) 1.8.1 | GPL-3.0, released 2026-06-16 | Sitemaps, indexes, compression, robots.txt discovery, feeds | GPL-3.0-or-later, which would reach everyone who installs `dossier`, as PyMuPDF's AGPL would have (spec 008). Fetches through `requests` unless given an adapter, and pulls `python-dateutil`. What `dossier` needs of a sitemap -- `<loc>` and `<lastmod>`, and an index's children -- is the standard library's `xml.etree` |
| [protego](https://github.com/scrapy/protego) 0.7 | BSD-3, released 2026-09-21, the Scrapy project's | robots.txt as RFC 9309 reads it: wildcards, `$`, longest match | Nothing. It parses text it is given, and never reaches the network. The standard library's `urllib.robotparser` matches by prefix alone, and reads `Disallow: /*.pdf$` as a path starting `/*.pdf$` |

**Chosen: `httpx`, the standard library's XML parser, and `protego`.**

**Existing options considered for politeness** (R1.35, R1.36), read from each
package's source on PyPI, 2026-09-27:

| Option | Covers | Missing |
|---|---|---|
| crawl4ai 0.9.4's `RateLimiter` | A per-domain wait, exponential backoff on `429` and `503`, three retries | It waits a random 1 to 3 s before every request whatever the site says, so `docs.astral.sh/uv` would take minutes, not seconds. It retries a `429` rather than stopping, and it reads no `Retry-After` and no `Crawl-delay`. It is not a separate package: taking it is taking crawl4ai, Playwright and a fork of `litellm` (the table above) |
| Scrapy 2.19's AutoThrottle and `RetryMiddleware` | A pace adjusted to the server's latency, and retries on `429` among eight statuses | Its `robots.txt` parsers read `Crawl-delay`, and nothing in Scrapy applies it; no `Retry-After`. And it is middleware for Scrapy's own engine, which a connector is not called by (the table above) |
| `protego`, already a dependency | `crawl_delay(user_agent)`: the `Crawl-delay` of the group that applies to `dossier` | Nothing: it is the half of R1.36 that is a site's to say |

**Chosen: `protego` for `Crawl-delay`**, and a stop and a wait written here:
what R1.35 and R1.36 add is a few dozen lines, and neither option does either
as specified.

## Must hold

### R1.1 — a connector never writes to the source system

`dossier` reads. No connector issues a create, update, delete or transition
against the system it reads from, including status-only side effects such as
marking a page as viewed.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors`)
- **Proved by:** `tests/unit/test_R001_1__connector_never_writes_to_the_source.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a full sync of `incidents-jira` against a recording transport | every request is `GET`; no `POST`, `PUT`, `PATCH` or `DELETE` |
| 2 | `attachments("INC-4821")` against the same transport | every request is `GET` |
| 3 | *counter-example* — the local ledger row for `INC-4821` is updated | allowed; the ledger is dossier's own state, not the source system |

### R1.2 — `fetch` returns the payload byte-for-byte as received

Normalisation happens later, in the ledger layer, for hashing only. It never
changes what is stored.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors`)
- **Proved by:** `tests/unit/test_R001_2__fetch_returns_payload_unmodified.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a transport returning JSON with keys in the order `summary, key, status` | `RawItem.payload` preserves that byte order; no re-serialisation |
| 2 | a payload with a UTF-8 BOM and CRLF line endings | both survive into `RawItem.payload` unchanged |
| 3 | a payload of `0` bytes | returned as `b""`, not as `None` and not as an error |
| 4 | *counter-example* — the hash recorded in the ledger for that item | computed over the *normalised* projection, not over these bytes (R2.3) |

### R1.3 — `list(since=None)` returns every item currently in scope

The full listing is what tombstoning is computed against, so an omission is
silently destructive.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors`)
- **Proved by:** `tests/unit/test_R001_3__list_without_since_returns_every_item.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a folder holding `audit-note.pdf` and two others | three `ItemRef`s |
| 2 | a Jira query matching 420 issues across 5 result pages | 420 `ItemRef`s; pagination is the connector's problem, not the caller's |
| 3 | a source whose scope currently matches nothing | an empty iterator, not an error |
| 4 | *counter-example* — an item deleted at the source yesterday | absent from the listing; the ledger tombstones it rather than the connector reporting it (R2.7) |

### R1.4 — `list(since=t)` returns a superset of the items changed at or after `t`

Returning extra items is correct and cheap. Omitting one is a defect that
presents as a document silently going stale.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors`)
- **Proved by:** `tests/unit/test_R001_4__list_since_returns_a_superset.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4822` changed `2026-08-05T16:02:00Z`, `since=2026-08-05T09:00:00Z` | `INC-4822` is in the result |
| 2 | `INC-4821` changed `2026-07-30T09:14:00Z`, `since=2026-08-05T09:00:00Z` | it may be present or absent; both are correct |
| 3 | an item changed exactly at `since` | present; the bound is inclusive |
| 4 | *counter-example* — a folder source, which has no change times | returns everything regardless of `since`; a superset is always a legal answer |

### R1.5 — a connector that cannot supply `remote_version` sets it to `None`

A fabricated version marker is worse than none: it makes R2.1 skip a fetch for an
item that did change.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors`)
- **Proved by:** `tests/unit/test_R001_5__absent_remote_version_is_none_not_invented.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `audit-note.pdf` from a folder source | `remote_version is None` |
| 2 | `OPS-114` from Confluence | `remote_version == "v37"` |
| 3 | a Jira issue whose response omits the `updated` field | `remote_version is None`, not the fetch time and not `""` |
| 4 | *counter-example* — the file's mtime on disk | not used as a version marker; it changes on copy and says nothing about content |

### R1.6 — attachments are addressable and versioned independently of their item

An issue can be untouched while the PDF attached to it was replaced.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors`)
- **Proved by:** `tests/unit/test_R001_6__attachments_are_versioned_independently.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` unchanged, its attachment `report.pdf` replaced | the attachment yields a new hash and a new snapshot (R2.6) |
| 2 | `INC-4821` changed, its attachment unchanged | the item is re-snapshotted; the attachment is not |
| 3 | two issues carrying byte-identical attachments | one snapshot, referenced twice; content addressing deduplicates |
| 4 | *counter-example* — an inline image embedded in the issue description | part of the item payload, not an attachment; it has no independent address |

### R1.7 — adding a connector requires no edit to the `dossier` core package

A new source type is a package declaring an entry point. If adding one means
touching a file under `src/dossier/`, the interface has failed.

- **Kind:** deterministic
- **Layer:** architecture
- **Proved by:** `tests/architecture/test_R001_7__connectors_are_resolved_only_by_entry_point.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `src/dossier/` scanned for connector type names | no `match` or `if` dispatching on `"jira"`, `"folder"` or `"confluence"` outside the entry-point registry |
| 2 | a third-party package declaring `dossier.connectors` entry point `sharepoint` | `type: sharepoint` in `sources.yaml` resolves with no change to dossier |
| 3 | *counter-example* — `dossier.infrastructure.connectors.folder` shipping in this package | allowed; it registers through the same entry point group as any third party, with no special case |

### R1.8 — credentials come from the environment, and never appear in config, logs, ledger or manifest

`sources.yaml` is committed to git. Anything in it is public to everyone with
repository access.

"The environment" is the one `dossier.config` reads everything else through:
the shell, with `.env` filling what the shell leaves unset (R9.11). A credential
is per machine exactly as an endpoint's key is, and a second place to keep one
would be a second place to lose one. `.env` yields only `DOSSIER_` variables, so
a credential that lives there is named with the prefix.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.credentials`)
- **Proved by:** `tests/unit/test_R001_8__credentials_never_reach_config_or_logs.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `sources.yaml` containing a `token:` key | load-time error naming the file and the key |
| 2 | `JIRA_TOKEN` set and a sync failing with an HTTP 401 | the error message contains the URL and the status, and not the token |
| 3 | a completed sync of `incidents-jira` | no ledger column and no manifest field holds the token |
| 4 | *counter-example* — the name `JIRA_TOKEN` appearing in `sources.yaml` as `token_env: JIRA_TOKEN` | allowed; naming the variable is not disclosing its value |
| 5 | `token_env: DOSSIER_JIRA_TOKEN`, `.env` in the workspace holding `DOSSIER_JIRA_TOKEN=…`, and the shell not setting it | `dossier sync` hands the connector that value; a credential is read through the same environment an endpoint is (R9.11) |
| 6 | *counter-example* — `token_env: JIRA_TOKEN`, with `JIRA_TOKEN=…` written only in `.env` | refused when the connector is built, naming `JIRA_TOKEN`; only `DOSSIER_` variables are read from `.env` (R9.11 row 4) |
| 7 | `token:` written on `procedures-confluence`, a `confluence` source | row 1's refusal suggests `token_env: DOSSIER_CONFLUENCE_TOKEN`: named for the source's own type, and with the prefix `.env` is read for. It once suggested `JIRA_TOKEN` to every source, a name row 6 refuses when it lives in `.env` |

### R1.9 — a connector error leaves the ledger unchanged for that item

Partial sync never records an item it did not successfully store.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync`)
- **Proved by:** `tests/unit/test_R001_9__failed_fetch_leaves_the_ledger_unchanged.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4822` raises a connection error during `fetch` | its ledger row keeps `content_hash=77c1b40a` and its previous `last_seen` |
| 2 | `INC-4901` is new and raises during `fetch` | no ledger row is created for it |
| 3 | `INC-4821` succeeds, then `INC-4822` fails | `INC-4821` is committed; the sync reports one failure and a non-zero exit code |
| 4 | *counter-example* — the failure happens after the snapshot is written but before the ledger row is updated | the ledger stays unchanged; the orphan snapshot is inert and is not referenced (R0.2, R2.8) |

### R1.10 — a connector declares the keys its sources take, and a source is checked against them at load time

A folder has a `path`, a Jira source a `query`. Those keys belong to one source
type, so its connector declares them -- as a model that refuses unknown keys --
and the loader checks each source against the shared keys plus its connector's
declaration before anything runs. The core never names a type's keys (R1.7), and
a misspelt key is still refused (R3.1): the declaration is what makes "unknown"
knowable for each type.

Checking a declaration imports the connector's package and does nothing else --
no connection, no credential (R3.8, R1.8).

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R001_10__connectors_declare_their_keys.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-manual` with `type: folder` and `path: inbox/incidents/` | accepted; `path` is a key the folder connector declares |
| 2 | `incidents-manual` with `type: folder` and no `path` | load-time error naming `sources.yaml`, the line and the missing `path` -- not a failure at the first sync (R3.1 row 2) |
| 3 | `incidents-manual` with `pth: inbox/incidents/` | load-time error naming `pth` and suggesting `path`, from the folder connector's declaration (R3.1 row 1) |
| 4 | a package declaring entry point `sharepoint` with its own keys | its sources load and are checked, with no edit to `dossier` (R1.7 row 2) |
| 5 | `type: sharepoint` with no package providing it | load-time error naming the type and the types available; a source cannot be checked against a declaration that does not exist |
| 6 | *counter-example* — `incidents-jira` with `watermark_overlap: 24h` | checked by the core as a duration, not by the connector; it is a shared key every source may carry (R2.4, R3.1 row 3) |

### R1.11 — a connector declares whether every listing it returns is complete

Tombstoning is a subtraction -- held minus listed -- and it is only safe against
a listing that omitted nothing (R1.3, R2.7). Sync can tell that a listing it
asked for with `since=None` is complete; it cannot tell that a connector would
have returned everything anyway. Before this rule the folder connector did
exactly that on every sync, and a file deleted from the folder stayed `active`
for ever, because the interface gave the connector no way to say so.

A connector that declares nothing is refused when it is built for a source,
before its first `list`, as a converter declaring no version is refused where
it is registered (R8.2 row 4). Defaulting an absent declaration to "may be
partial" would be safe, and would silently keep the bug this rule exists to
close for every folder-like connector written outside this repository.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors`)
- **Proved by:** `tests/unit/test_R001_11__a_connector_declares_whether_its_listings_are_complete.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the folder connector | `lists_everything` is `True`; `list(since=2026-08-05T09:00:00Z)` and `list(None)` yield the same three `ItemRef`s (R1.4 row 4) |
| 2 | the Jira connector | `lists_everything` is `False`; `since` narrows its JQL |
| 3 | a connector declaring nothing, built for `incidents-manual` | refused with an error naming the source, its type and `lists_everything`; `list` is never called |
| 4 | *counter-example* — the Jira connector asked with `since=None` | that one listing is complete, but the declaration stays `False`; it describes the type, and completeness of a call is sync's to decide (R2.21) |

### R1.12 — a Jira source authenticates as its keys say: Bearer with a token alone, Basic with a user beside it

Jira Data Center accepts a personal access token as `Authorization: Bearer`.
Jira Cloud accepts an API token only as HTTP Basic, `email:token`, and Data
Center accepts Basic too, with a username and password. Which scheme a request
carries is decided by what the source names: `token_env` alone is Bearer;
`user_env` named beside it is Basic. The user is resolved the way the token is
-- named in `sources.yaml`, read from the environment when the connector is
built, never written into config, logs, ledger or manifest (R1.8).

There is no probing. A connector that sent the token as Bearer, was refused, and
sent it again as Basic would put a credential on the wire twice in two forms to
a server that has just declined it, and would make a 401 mean two things. A
refusal names the URL and the status (R1.8 row 2), and the fix is a key in
`sources.yaml`.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.jira`)
- **Proved by:** `tests/unit/test_R001_12__a_jira_source_authenticates_as_its_keys_say.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `token_env: DOSSIER_JIRA_TOKEN` and no `user_env` | every request carries `Authorization: Bearer <token>` |
| 2 | `user_env: DOSSIER_JIRA_USER` and `token_env: DOSSIER_JIRA_TOKEN` | every request carries `Authorization: Basic <base64 of user:token>` |
| 3 | `user_env` named and its variable unset | refused when the connector is built, naming the variable, before any request -- as an unset `token_env` is (R1.8) |
| 4 | *counter-example* — a Bearer request answered 401 | reported with the URL and the status, and not retried as Basic |
| 5 | *counter-example* — `user_env` without `token_env` | load-time error naming the source and both keys (R1.10): a user with no token is half a credential |
| 6 | *counter-example* — neither key named | no `Authorization` header; a Jira open to anonymous reads is reachable as such |

### R1.13 — a Jira source declares its deployment, and the listing route follows it

Jira Data Center lists issues at `GET /rest/api/2/search`, paginated by
`startAt` against `total`. Jira Cloud has retired that route: it lists at
`GET /rest/api/2/search/jql`, paginated by the `nextPageToken` each page hands
back until a page says `isLast`. Fetching an issue and listing or fetching its
attachments are the same on both. A source says which it reaches with
`deployment: datacenter` or `deployment: cloud`; absent means `datacenter`, the
deployment this project reads. Nothing is inferred from the hostname: an
inference is a second thing to be wrong about when the route answers 410.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.jira`)
- **Proved by:** `tests/unit/test_R001_13__a_jira_source_declares_its_deployment.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `deployment: datacenter`, or the key absent, and a query matching 420 issues | `GET …/rest/api/2/search` with `startAt` 0, 50, … 400; 420 `ItemRef`s (R1.3 row 2) |
| 2 | `deployment: cloud` and a query answered in three pages | `GET …/rest/api/2/search/jql` three times; the second and third carry the `nextPageToken` the page before handed back; the listing ends at the page that says `isLast` |
| 3 | `deployment: cloud` and `INC-4821` fetched | `GET …/rest/api/2/issue/INC-4821`, the route Data Center uses |
| 4 | *counter-example* — `deployment: server` | load-time error naming the key and the two values it takes (R1.10) |
| 5 | *counter-example* — `list(since=t)` on either deployment | the same widened `updated >=` clause (R1.4); the deployment changes the route, never the query |

### R1.14 — a Jira issue is reported as `application/vnd.dossier.jira-issue+json`, never as `application/json`

A media type chooses a converter (R8.3), and the pair is the whole type. A
converter claiming `application/json` would claim every JSON document any source
ever holds -- a webhook body, a configuration export, a Confluence page -- and read
each as though Jira had written it. The issue is labelled with what wrote it, so
that the converter reading it claims Jira issues and nothing else (R8.16). A file
an issue carries is still what Jira says that file is (R2.16).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.jira`), naming the type the domain declares (`dossier.domain.conversion.JIRA_ISSUE`)
- **Proved by:** `tests/unit/test_R001_14__a_jira_issue_is_reported_as_a_jira_issue.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` fetched | `media_type` `application/vnd.dossier.jira-issue+json`, and the payload the bytes Jira sent (R1.2) |
| 2 | *counter-example* — `INC-4821/report.pdf` fetched, Jira reporting `application/pdf` | `application/pdf`; what the issue carries is labelled by what Jira says it is, not by the issue (R2.16) |
| 3 | *counter-example* — a folder source holding `export.json` | `application/json`, as R2.16 assigns it; a folder has only the name to go on and cannot know what wrote the file |

### R1.15 — a Confluence source lists the pages its CQL query matches, and nothing else the query matches

The connector asks `GET /rest/api/content/search` with the source's `query` and
`type = page` added to it. It pages by `start` and `limit` until a page of
results names no `next`. A CQL query matches comments, attachments and blog posts
as readily as pages. An attachment is reached through the page that carries it
(R1.18), and the rest are not held.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`)
- **Proved by:** `tests/unit/test_R001_15__a_confluence_source_lists_the_pages_its_query_matches.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `query: space = OPS`, matching 120 pages | `cql=(space = OPS) AND type = page`, asked with `start` 0, 50 and 100; 120 `ItemRef`s; the listing ends at the page of results with no `_links.next` |
| 2 | `list(since=2026-08-06T09:00:00Z)` | the CQL gains `AND lastmodified >= "2026-08-05 09:00"`, widened by a day as a Jira window is, because CQL reads a bare time in the server's zone (R1.4) |
| 3 | *counter-example* — a comment and an attachment in `OPS`, both matched by `space = OPS` | neither is listed |
| 4 | *counter-example* — the connector's declaration | `lists_everything` is `False`, because `since` narrows its CQL (R1.11) |

### R1.16 — a Confluence page is keyed by its id, and its marker is its version number

`v37` and not `37`, so a page's marker reads as a version beside a file's
`81920301:v2` (R1.18). It is Confluence's own number, written as Confluence
writes it in a page's history, and no marker is made up for a page without one
(R1.5).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`)
- **Proved by:** `tests/unit/test_R001_16__a_confluence_page_is_keyed_by_its_id.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `OPS-114`: id `81920114`, version 37, `version.when` `2026-08-05T16:02:00.000Z` | `ItemRef` with key `81920114`, `remote_version` `v37`, `updated_at` `2026-08-05T16:02:00Z` |
| 2 | `OPS-114` edited, now at version 38 | `remote_version` `v38`, so the page is fetched again (R2.1) |
| 3 | *counter-example* — `OPS-114` renamed `OPS-114 Escalation procedure (2026)` at version 38 | the key stays `81920114`: one changed item, not a tombstone and a new one (R2.7) |

### R1.17 — a Confluence page is fetched as Confluence renders it for export, and labelled a Confluence page

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`), naming the type the domain declares (`dossier.domain.conversion.CONFLUENCE_PAGE`)
- **Proved by:** `tests/unit/test_R001_17__a_confluence_page_is_fetched_rendered.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `fetch("81920114")` | `GET …/rest/api/content/81920114?expand=body.export_view,version,space`; the payload the bytes Confluence sent (R1.2), `media_type` `application/vnd.dossier.confluence-page+json` |
| 2 | *counter-example* — the page's table of contents, whose class name holds the time it was rendered | stored as sent, table of contents included. What reaches a stage is the converter's decision (R8.20); a payload edited here would be hashed from bytes nobody received |
| 3 | *counter-example* — `81920114/escalation-matrix.png`, which Confluence reports as `image/png` | `image/png`; a file is labelled by what Confluence says it is (R2.16), not by its page |

### R1.18 — a page's files are addressed `<page id>/<filename>`, and a file's marker is its attachment id and version

When a file is uploaded again under the same name, Confluence keeps the
attachment's id and raises its version. A file deleted and uploaded again gets a
new id and starts again at version 1. The id alone would miss the first case, and
the version alone would miss the second.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`)
- **Proved by:** `tests/unit/test_R001_18__a_pages_files_are_addressed_and_versioned.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `escalation-matrix.png` on `81920114`, attachment id `81920301`, version 2 | `AttachmentRef` with key `81920114/escalation-matrix.png`, `item_key` `81920114`, `remote_version` `81920301:v2` |
| 2 | the file uploaded again, now version 3, with the page untouched at `v37` | `81920301:v3`: the file is fetched and the page is not (R2.6) |
| 3 | `fetch("81920114/escalation-matrix.png")` | a `GET` of the base URL joined to the attachment's `_links.download`, the bytes as sent, labelled as Confluence reports the file (R2.16) |
| 4 | a page carrying 30 files, listed 25 at a time | both pages of the listing are read, giving 30 refs |
| 5 | *counter-example* — the file deleted at version 1 and uploaded again at version 1 | a new id, `81920377:v1`. The version alone reads `v1` both times, and R2.1 would skip the fetch |
| 6 | a page carrying 30 files, all of them fetched in one sync | the page's files are listed once, not once more for each file fetched. Synced from cwiki, KIP-1279's 66 images cost about 130 listing requests before this row |

### R1.19 — with `export: pdf`, a page also carries its PDF export, keyed `<page id>.pdf`

The export's marker is the page's marker, followed by `+` and the first twelve hex
digits of the SHA-256 of the page's file markers, sorted and joined by newlines.
A page carrying no files has just the page's marker. The composition is a pure
decision and lives in the domain.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`), with the marker from the domain (`dossier.domain.confluence.export_version`)
- **Proved by:** `tests/unit/test_R001_19__a_page_carries_its_pdf_export.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `export: pdf`, and `81920114` at `v37` carrying `escalation-matrix.png` | `attachments("81920114")` yields `81920114/escalation-matrix.png` and `81920114.pdf`, both carried by `81920114`; the export's marker is `v37+` and twelve hex digits |
| 2 | `fetch("81920114.pdf")` | `GET …/spaces/flyingpdf/pdfpageexport.action?pageId=81920114` with `X-Atlassian-Token: no-check`, and the redirect followed in the same session; the PDF's bytes, labelled `application/pdf` |
| 3 | `escalation-matrix.png` uploaded again, and the page still at `v37` | the export's marker moves, and the export is fetched again: the PDF draws the image |
| 4 | *counter-example* — `export: pdf`, and a page carrying no files | the export's marker is `v37` |
| 5 | *counter-example* — no `export:` | no `81920114.pdf`, and no export is asked for |
| 6 | *counter-example* — `export: pdf` removed after a sync | at the next sync, every `<page id>.pdf` is tombstoned, as a file its page no longer carries (R2.6 row 3). The next sync lists every page because a key of the source changed (R2.24) |
| 7 | *counter-example* — `export: docx` | load-time error naming the key and the one value it takes (R1.10) |

### R1.20 — an export that is refused, or answered with anything but a PDF, fails that document and says why

`export: pdf` is the workspace's statement that the server exports. When the
server does not, the fix is a key in `sources.yaml` or a permission on the
server. Neither can be made from inside the connector, as R1.12 found for a
refused credential.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`)
- **Proved by:** `tests/unit/test_R001_20__a_refused_export_fails_its_document.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `export: pdf`, against a server that answers the export `403` | `81920114.pdf` fails with the URL, `403`, and that `export: pdf` asks for an export this server refuses. The page and its files are held (R1.9), and the watermark stays where it was (R2.8) |
| 2 | *counter-example* — the export answered `200` with Confluence's login page, as `text/html` | the document fails, naming the type it got. A login page is never stored as a PDF |
| 3 | *counter-example* — that `403`, at the next sync | asked again as before, once, whether or not the listing returns the page (R2.23). Not retried without the header, and not dropped from the listing: a PDF missing without a word reads exactly like a page that has none |

### R1.21 — a Confluence source authenticates as a Jira source does

`token_env` alone means Bearer, `user_env` beside it means Basic, and neither
means anonymous. A user with no token is refused at load time (R1.12). Data
Center takes a personal access token as Bearer. Cloud takes an API token only
as Basic, `email:token`. One function decides the header for both connectors,
so the two cannot drift apart.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`)
- **Proved by:** `tests/unit/test_R001_21__a_confluence_source_authenticates_as_jira_does.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `token_env: DOSSIER_CONFLUENCE_TOKEN` and no `user_env` | every request carries `Authorization: Bearer <token>`, the export's redirect included |
| 2 | `user_env: DOSSIER_CONFLUENCE_USER` and `token_env: DOSSIER_CONFLUENCE_TOKEN` | every request carries `Authorization: Basic <base64 of user:token>` |
| 3 | *counter-example* — neither key named | no `Authorization` header: `cwiki.apache.org` serves its pages to an anonymous reader |
| 4 | *counter-example* — `user_env` without `token_env` | load-time error naming the source and both keys (R1.10) |

### R1.22 — a windowed Confluence listing also lists each page the query matches whose files changed in the window

CQL's `lastmodified` on a page moves with the page's own version and not with
its files. This was checked against Confluence Data Center 9.2.21, run in Docker
on 2026-09-27. A page created at 10:07 was given a file at 10:18, and the same
file was uploaded again at 11:17. The page stayed at version 1 with
`lastmodified` 10:07. A `type = page` search from 11:15 returned nothing, and a
`type = attachment` search from 11:15 returned the file at version 2, with the
page as its container. So a windowed listing left the page out, its files were
never asked for, and R1.18 row 2 held only under a complete listing (R2.22,
R2.24).

A windowed listing therefore asks a second question: which files changed in the
window (`type = attachment AND lastmodified >= <floor>`, from the same floor
R1.4 sets). Each of their pages is then checked against the source's query
(`(<query>) AND type = page AND id in (...)`), and every page that matches is
listed once. The query is never applied to the files themselves: a
`label = runbook` query matches pages and not the files on them, so it would
find no file at all.

A file removed from a page does not move the page either. A removed file is
absent from search, so this question cannot see a removal. A complete listing
lists the page, and its files are settled then (R2.6 row 3, R2.22).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`)
- **Proved by:** `tests/unit/test_R001_22__a_windowed_listing_finds_pages_whose_files_changed.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `81920114` at `v37`, last edited before the window; `escalation-matrix.png` uploaded again inside it, now `81920301:v3` | the windowed listing yields `81920114` once, with marker `v37`; the file is fetched and the page is not (R1.18 row 2, R2.1) |
| 2 | `81920114` edited inside the window, and its file uploaded again inside it too | listed once, not twice |
| 3 | files changed inside the window on 60 pages the query matches | the pages are asked about 50 ids at a time, in two requests, and all 60 are listed |
| 4 | *counter-example* — a file uploaded again inside the window on a page in another space, outside `space = OPS` | not listed: the source's query decides which pages are in scope (R1.3) |
| 5 | *counter-example* — `list(since=None)` | no file is searched for, since a complete listing already lists every page |
| 6 | *counter-example* — `escalation-matrix.png` removed from `81920114` inside the window | `81920114` is not listed by this rule. The file is tombstoned by the next complete listing (R2.22) |

### R1.23 — with `comments: true`, a page's payload also holds its comments, replies included

A Confluence source may say `comments: true`. A page is then held with every
comment on it, as
`GET /rest/api/content/{id}/child/comment?depth=all&expand=body.export_view,version,history,ancestors`
answers them, one answer after another until none names a `next`. The payload is
one JSON object holding each answer byte for byte, as Confluence sent it:
`{"page": <the page>, "comments": [<each answer, in the order asked>]}`. It keeps
the page's media type, so the converter that claims a page claims it, and reads
either shape (R8.30). `comments` defaults to `false`. Then no comment is asked
for, and a page is held as R1.17 holds it.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`)
- **Proved by:** `tests/unit/test_R001_23__a_page_can_be_held_with_its_comments.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `comments: true`, and `81920114` carrying `m.keller`'s comment `81920501` and `a.aleks`'s reply `81920502` | `fetch("81920114")` asks for the page, then for `…/81920114/child/comment?depth=all`, and holds `{"page": …, "comments": [<the answer>]}`, each part the bytes Confluence sent, the reply in it |
| 2 | 60 comments on the page, 50 to an answer | both answers are held, in the order they were asked for (R1.3) |
| 3 | *counter-example* — no `comments:` | the payload is the page as sent (R1.17), and no comment is asked for |
| 4 | *counter-example* — `comments: maybe` | a load-time error naming the key (R1.10) |

### R1.24 — with `comments: true`, a page's marker moves when a comment on it is added, edited or removed

The page's marker is its version, followed by `+c` and the first twelve hex
digits of the SHA-256 of its comments' ids and versions, each `<id>:v<n>`, sorted
and joined by newlines. A page with no comment keeps its version alone, so
turning `comments:` on fetches again only the pages that have one. A listing asks
which comments its pages carry once for every 50 pages, with
`type = comment AND container in (…)`, and not once a page. A reply's container
is its page. The composition is a pure decision and lives in the domain.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`), with the marker from the domain (`dossier.domain.confluence.commented_version`)
- **Proved by:** `tests/unit/test_R001_24__a_pages_marker_moves_with_its_comments.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `81920114` at `v37`, with `81920501` at version 2 and `81920502` at version 1 | `v37+c` and twelve hex digits |
| 2 | `81920502` edited, now at version 2, and the page still at `v37` | the marker moves, and the page is fetched again (R2.1) |
| 3 | `81920502` removed | the marker moves |
| 4 | 120 pages listed | their comments are asked for 50 pages at a time, in three searches |
| 5 | *counter-example* — `comments: true`, and a page with no comment | `v37` |
| 6 | *counter-example* — no `comments:` | `v37`, whatever comments the page has, and no comment is searched for |

### R1.25 — with `comments: true`, a windowed listing also lists each page the query matches whose comments changed in the window

R1.22's second question then asks for files and comments together:
`type in (attachment, comment) AND lastmodified >= <floor>`. A removed comment is
absent from search, as a removed file is. The next complete listing settles it
(R2.22).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`)
- **Proved by:** `tests/unit/test_R001_25__a_windowed_listing_finds_pages_whose_comments_changed.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `81920114` at `v37`, last edited before the window, and `81920501` added inside it | listed once, with its `+c` marker, and fetched |
| 2 | `81920502`, a reply, added inside the window | the same: the reply's container is the page |
| 3 | *counter-example* — no `comments:` | the question is R1.22's, `type = attachment` alone |
| 4 | *counter-example* — `81920502` removed inside the window | not listed by this rule; the next complete listing lists the page with its new marker (R2.22) |

### R1.26 — a page that includes another page's text has a marker that moves with what it includes

The page's marker is its version, followed by `+i` and the first twelve hex
digits of the SHA-256 of what it includes, each `<id>:v<n>`, sorted and joined by
newlines. That covers `include` and `excerpt-include`, whichever part of the page
is drawn. Inclusions are followed through the included pages, because Confluence
draws those too, and each page is counted once. An include naming a page that
cannot be found counts as `missing:<space>/<title>`, so the marker moves when the
page appears. A page including nothing keeps its version alone. With
`comments: true` as well, `+i…` comes before `+c…`.

A listing asks which of the query's pages use either macro,
`(<query>) AND type = page AND macro in (include, "excerpt-include")`, with the
storage format of each, where the pages they name are written. It then asks for
those pages by space and title. A title names no space when the page is in the
including page's own. Both searches are asked at every sync, windowed or not.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`), with the marker from the domain (`dossier.domain.confluence.including_version`)
- **Proved by:** `tests/unit/test_R001_26__a_pages_marker_moves_with_what_it_includes.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `81920114` at `v37`, including `Escalation contacts`, `81920130` at version 2 | `v37+i` and twelve hex digits |
| 2 | `Escalation contacts` edited to version 3, and `81920114` still at `v37` | `81920114`'s marker moves, and it is fetched again (R2.1) |
| 3 | `81920114` includes `Escalation contacts`, which includes `On-call rota`, `81920131`, and the rota is edited | `81920114`'s marker moves |
| 4 | an include naming `Escalation contacts` in space `ENG`, which has no such page | the marker counts `missing:ENG/Escalation contacts` |
| 5 | *counter-example* — a page including nothing | `v37` |
| 6 | *counter-example* — `Escalation contacts` includes `81920114` back | each page is counted once, and the listing ends |

### R1.27 — a windowed listing also lists each page the query matches that includes a page changed in the window

An including page is listed when any page it includes, directly or through
another, was last changed at or after the window's floor (R1.4). The included
page need not be in the query's scope: a page in another space draws into this
one all the same.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.confluence`)
- **Proved by:** `tests/unit/test_R001_27__a_windowed_listing_finds_pages_whose_included_text_changed.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `81920114` at `v37`, last edited before the window, and `Escalation contacts` edited inside it | `81920114` listed once, with its `+i` marker |
| 2 | `Escalation contacts` in space `ENG`, outside `space = OPS`, edited inside the window | `81920114` is listed. `Escalation contacts` is not, because the query decides what is held (R1.3) |
| 3 | *counter-example* — nothing `81920114` includes changed inside the window | not listed by this rule |
| 4 | *counter-example* — `list(since=None)` | every page listed once, each including one with its `+i` marker |

### R1.28 — a Jira issue is fetched with `expand=names,schema`, so its payload says what each custom field is called and holds

A custom field arrives as `customfield_10050` in an issue's `fields`. What a
person calls it, and what kind of value it holds, come only when the fetch asks.
`names` maps each field to its name, and `schema` to its type. Read against a
Jira Software Data Center 10.3 in Docker on 2026-09-27: without `expand`, the
payload had neither. With it, `customfield_10000` was `Development`, of type
`any`, and held a Java object's string of 3 KB (R8.31). The listing asks for no
expansion, because `names` and `schema` would then come once for every issue
listed.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.jira`)
- **Proved by:** `tests/unit/test_R001_28__an_issue_is_fetched_with_its_field_names.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `fetch("INC-4821")` | `GET …/rest/api/2/issue/INC-4821?expand=names,schema`, and the payload as sent, `names` and `schema` in it |
| 2 | *counter-example* — the listing | asks `fields=updated,attachment`, and no `expand` (R1.13) |
| 3 | *counter-example* — `fetch("INC-4821/report.pdf")` | the file's bytes, as before. A file has no fields |

### R1.29 — a web source lists every URL its sitemap names under its `url`, and nothing else

A sitemap index is followed to each sitemap it names on the same host. A sitemap
that cannot be read fails the listing: the listing is complete, and an empty one
would tombstone every page held (R1.11, R2.7).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.web`), with the scope from the domain (`dossier.domain.web.in_scope`)
- **Proved by:** `tests/unit/test_R001_29__a_web_source_lists_what_its_sitemap_names.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `vendor-docs`, and a sitemap naming `…/ops/`, `…/ops/escalation` and `…/ops/runbooks/dns-failover.html` | three `ItemRef`s, sorted by key |
| 2 | `sitemap.xml` an index naming `sitemap-ops.xml` and `sitemap-blog.xml` | both are read, and the pages under `…/ops/` in either are listed |
| 3 | the sitemap served gzip-compressed, as `sitemap.xml.gz` | read as if it were not |
| 4 | `lists_everything` | `True`: `list(since=2026-08-05T09:00:00Z)` yields what `list(None)` does, and a page gone from the sitemap is tombstoned at the next sync (R2.7) |
| 5 | *counter-example* — `https://docs.example.org/blog/release-notes`, `https://other.example.net/ops/escalation`, and `…/ops/escalation?lang=de` in the sitemap | none is listed: outside the prefix, on another host, and carrying a query |
| 6 | *counter-example* — the sitemap answered `404` | the listing fails, naming the sitemap's URL and `404`; nothing held is tombstoned |
| 7 | *counter-example* — an index naming a sitemap on another host | not read |

### R1.30 — a web page is keyed by its URL relative to the source's `url`, with `index` for a directory

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.web.page_key`)
- **Proved by:** `tests/unit/test_R001_30__a_web_page_is_keyed_by_its_relative_url.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `https://docs.example.org/ops/escalation` | `escalation` |
| 2 | `https://docs.example.org/ops/runbooks/dns-failover.html` | `runbooks/dns-failover.html` |
| 3 | `https://docs.example.org/ops/`, the prefix itself | `index` |
| 4 | `https://docs.example.org/ops/runbooks/` | `runbooks/index` |
| 5 | `url: https://docs.example.org/ops`, without the slash | the same keys as rows 1-4; `…/opsx/guide` is not in scope |
| 6 | *counter-example* — `…/ops/escalation#contacts` | `escalation`; a fragment is not an address |
| 7 | *counter-example* — `…/ops/runbooks/` and `…/ops/runbooks/index` both in the sitemap | the listing fails, naming both URLs and `runbooks/index`; one key cannot hold two pages |

### R1.31 — a web page's marker is its sitemap `<lastmod>`, and `None` without one

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.web`), with the parse from the domain (`dossier.domain.web.sitemap`)
- **Proved by:** `tests/unit/test_R001_31__a_web_pages_marker_is_its_lastmod.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `…/ops/escalation` with `<lastmod>2026-08-05T16:02:00+00:00</lastmod>` | `remote_version == "2026-08-05T16:02:00+00:00"`, and `updated_at` that time |
| 2 | `<lastmod>2026-08-05</lastmod>`, a date alone | `remote_version == "2026-08-05"`, and `updated_at` midnight UTC that day |
| 3 | `fetch("escalation")` | the same marker as the listing gave |
| 4 | *counter-example* — `…/ops/runbooks/dns-failover.html` with no `<lastmod>` | `remote_version is None`, not the fetch time; its bytes decide whether it changed (R1.5, R2.2) |
| 5 | *counter-example* — `<lastmod>last week</lastmod>` | `remote_version == "last week"`, `updated_at is None`. A marker is compared, never read as a time (R2.1) |

### R1.32 — a web page is labelled with the media type its `Content-Type` header states

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.web`)
- **Proved by:** `tests/unit/test_R001_32__a_web_page_is_labelled_as_its_server_says.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `escalation` served `text/html; charset=utf-8` | `media_type == "text/html"`, and the payload the bytes as sent (R1.2) |
| 2 | `escalation-matrix.pdf` served `application/pdf` | `application/pdf` |
| 3 | `attachments("escalation")` | nothing: a web page carries no files |
| 4 | *counter-example* — `runbooks/dns-failover.html` served `text/plain` | `text/plain`; a name is not evidence about content (R2.16) |
| 5 | *counter-example* — a response with no `Content-Type` | `application/octet-stream`, the type nothing claims (R8.5) |

### R1.33 — a URL the host's `robots.txt` disallows for `dossier` is neither listed nor fetched

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.web`)
- **Proved by:** `tests/unit/test_R001_33__a_web_source_honours_robots_txt.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `robots.txt` holding `User-agent: *` and `Disallow: /ops/drafts/`, and the sitemap naming `…/ops/drafts/escalation-v2` | not listed; the other pages are |
| 2 | `fetch("drafts/escalation-v2")` against the same `robots.txt` | fails naming the URL and `robots.txt`; no request is made for the page |
| 3 | `Disallow: /*.pdf$` for `User-agent: dossier` only | `escalation-matrix.pdf` is not listed; `escalation` is |
| 4 | *counter-example* — `robots.txt` answered `404` | every page in scope is listed |
| 5 | *counter-example* — `robots.txt` answered `503` | the listing fails, naming `robots.txt` and `503`; nothing held is tombstoned |

### R1.34 — a web page is followed through redirects only within the source's `url`

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.web`)
- **Proved by:** `tests/unit/test_R001_34__a_web_page_redirects_only_within_its_source.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `…/ops/escalation` answered `301` to `…/ops/escalation/` | the bytes of `…/ops/escalation/`, under the key `escalation` |
| 2 | a chain of six redirects within `…/ops/` | fails after the fifth, naming the page's URL |
| 3 | *counter-example* — `…/ops/escalation` answered `302` to `https://docs.example.org/login?next=/ops/escalation` | fails, naming both URLs; the login page is not stored |
| 4 | *counter-example* — `http://docs.example.org/sitemap.xml` answered `301` to its `https` form | followed; the sitemap may move within its host |

### R1.35 — once its site answers `429`, a web source asks it nothing more that sync

The request answered `429 Too Many Requests` fails, naming its URL and the
status. Every request the connector would make after it fails without being
sent, naming the URL that was refused and `delay:` (R1.36). Sync owes each page
that fails (R2.23). The refusal lasts as long as the connector, which is one
sync.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.web`)
- **Proved by:** `tests/unit/test_R001_35__a_web_source_stops_asking_a_site_that_answered_429.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `escalation` answered `429`, then `fetch("index")` | fails naming `https://docs.example.org/ops/escalation`, `429` and `delay:`; `…/ops/` is not asked for |
| 2 | a sync of `vendor-docs` in which `escalation-matrix.pdf` is answered `429` | `escalation` is stored; `escalation-matrix.pdf`, `index` and `runbooks/dns-failover.html` fail and are owed (R2.23), and the site sees no request after the one it refused |
| 3 | `robots.txt` answered `429` | the listing fails naming `robots.txt` and `429`; the sitemap is not asked for, and nothing held is tombstoned |
| 4 | *counter-example* — the next sync's connector, after this one was refused | asks the site again: a refusal lasts one sync |
| 5 | *counter-example* — `escalation` answered `404` | only `escalation` fails; `index` is asked for and fetched. A missing page says nothing about how often a site may be asked |

### R1.36 — a web source starts each request to its site at least the longer of its `delay:` and the site's `Crawl-delay` after the one before

`delay:` is a number of seconds, no less than 0, and absent means none.
`Crawl-delay` is what the host's `robots.txt` gives the user agent `dossier`, as
`protego` reads it, and it holds from the first request after `robots.txt`. A
redirect's hops are requests like any other (R1.34). With neither, requests go
back to back.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.web.spacing`), waited for in infrastructure (`dossier.infrastructure.connectors.web`)
- **Proved by:** `tests/unit/test_R001_36__a_web_source_spaces_its_requests.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `delay: 2`, and a `robots.txt` with no `Crawl-delay`, then `fetch("escalation")` | `robots.txt`, the sitemap and `…/ops/escalation` are asked 2 s apart: two waits of 2 s |
| 2 | `Crawl-delay: 5` under `User-agent: *`, and no `delay:` | two waits of 5 s: the sitemap after `robots.txt`, and `escalation` after the sitemap |
| 3 | `delay: 2` and `Crawl-delay: 5` | waits of 5 s: a source asks no faster than its site asks |
| 4 | `delay: 10` and `Crawl-delay: 5` | waits of 10 s: and may ask more slowly |
| 5 | `delay: 2`, and `escalation` answered `301` to `…/ops/escalation/` | `…/ops/escalation/` is asked 2 s after `…/ops/escalation` |
| 6 | *counter-example* — neither `delay:` nor `Crawl-delay` | no wait at all: `robots.txt`, the sitemap and `escalation` back to back |
| 7 | *counter-example* — `delay: -1`, or `delay: soon` | `sources.yaml` is refused, naming `vendor-docs` and `delay` (R1.10) |

### R1.37 — with `crawl:`, a web source lists every page its links reach within its `url`, and reads no sitemap

The crawl starts at `url`. It follows the `href` of every `<a>` in an HTML page,
resolved against the page's `<base>`, or failing one, the URL the page was
answered at. It follows only links under `url`, as R1.29 reads them, and asks
each URL once.

- **What is listed.** Every URL answered as a page. Each is keyed by the URL it
  was answered at, after any redirect within `url` (R1.30), and has no marker
  (R1.31).
- **What is left out.** A link answered with a `4xx` other than `429`, or one
  that redirects out of `url`, is not a page. It is not listed, and the crawl
  goes on.
- **`fetch`** returns the bytes the crawl was answered, and asks nothing.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.web.links`, `dossier.domain.web.Frontier`), asked for in infrastructure (`dossier.infrastructure.connectors.web`)
- **Proved by:** `tests/unit/test_R001_37__a_web_source_crawls_its_links.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `vendor-docs` with `crawl: 50`, its pages linked as the fixtures say | `escalation`, `escalation-matrix.pdf`, `index`, `runbooks/dns-failover.html`. The sitemap is not asked, and neither is `/blog/release-notes` |
| 2 | that source synced | each page is asked once, and `fetch` asks nothing |
| 3 | that source synced again, with nothing changed | each page is asked once more, and no snapshot is written (R2.2) |
| 4 | `index` also links `escalation#paging` and `https://DOCS.example.org/ops/escalation` | one page, `escalation`, asked once |
| 5 | `escalation` answered with a redirect to `…/ops/escalation/` | one page, keyed `escalation/index`. A link elsewhere to `…/ops/escalation/` is not asked again |
| 6 | a page whose `<base href="https://docs.example.org/ops/runbooks/">` precedes a link to `dns-failover.html` | `runbooks/dns-failover.html` is listed |
| 7 | *counter-example* — `escalation-matrix.pdf`, whose bytes spell `<a href="hidden">` | listed, and not read for links: `…/ops/hidden` is not asked |
| 8 | *counter-example* — `index` also links `old-runbook`, answered `404` | `old-runbook` is not listed; the other four are |
| 9 | *counter-example* — `index` also links `login`, which redirects to `https://sso.example.org/login` | `login` is not listed, and `sso.example.org` is not asked |
| 10 | *counter-example* — `escalation` links `drafts/escalation-v2`, which `robots.txt` disallows | neither asked nor listed (R1.33) |
| 11 | *counter-example* — `index` also links `escalation?print=1` | not asked (R1.29 row 5) |

### R1.38 — a crawl that cannot finish fails the listing, and lists nothing

A crawl's listing is complete, and a held page missing from it is tombstoned
(R1.11, R2.7). So a crawl that cannot tell it has reached every page fails the
listing and names why. That happens when:

- `url` itself is not a page, or `robots.txt` disallows it;
- a page answers `5xx` or `429` (R1.35), or does not answer;
- a page redirects more than five times (R1.34);
- one more URL is left to ask once `crawl:` URLs have been asked.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.web.Frontier`), asked for in infrastructure (`dossier.infrastructure.connectors.web`)
- **Proved by:** `tests/unit/test_R001_38__a_crawl_that_cannot_finish_fails_the_listing.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `crawl: 3`, and the four pages of R1.37 row 1 | the listing fails, naming `3` and the URL it would have asked next. Three pages were asked, and the held pages stay active |
| 2 | `escalation` answered `503` | the listing fails, naming `…/ops/escalation` and `503`, and the held pages stay active |
| 3 | `escalation` answered `429` | the listing fails, and nothing more is asked (R1.35) |
| 4 | `…/ops/` itself answered `404` | the listing fails, naming it: a crawl that reaches nothing is not an empty site |
| 5 | `robots.txt` disallowing `/ops/` | the listing fails, naming `…/ops/` and `robots.txt`: a crawl that may not start reaches nothing |
| 6 | *counter-example* — `crawl: 4` and the same four pages | all four listed: a crawl that has asked exactly `crawl:` URLs, with none left, has finished |

### R1.39 — `crawl:` is a whole number of URLs, at least 1, and a source says `crawl:` or `sitemap:`, never both

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.connectors.web.WebKeys`)
- **Proved by:** `tests/unit/test_R001_39__crawl_is_a_number_of_urls_and_not_a_sitemap.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `crawl: 0` | `sources.yaml` is refused, naming `vendor-docs` and `crawl` (R1.10) |
| 2 | `crawl: true`, or `crawl: all`, or `crawl: 2.5` | refused the same way: `crawl:` is how many URLs to ask, not a switch |
| 3 | `crawl: 50` and `sitemap: https://docs.example.org/sitemap.xml` | refused, naming both keys: a source is listed one way |
| 4 | *counter-example* — neither | listed from the host's sitemap (R1.29) |

## Open questions

| # | Question | Resolution |
|---|----------|------------|
| 1 | Does the connector read Confluence Cloud? Cloud still answers the version-1 content routes under `/wiki`, but its PDF export is an asynchronous task that is started and then polled | OPEN — needs a Cloud site to run against. The connector is read against Data Center 9.2 (`cwiki.apache.org`, `confluence.atlassian.com`, and one in Docker). Kept open on 2026-09-27: no source this project reads is on Cloud |
| 2 | Should a page's comments be part of its document? `expand=children.comment.body.export_view` would bring them into the payload, which gives every held page a new snapshot | RESOLVED by R1.23 to R1.25 and R8.30 — yes, when a source asks: `comments: true`, off by default. Decided 2026-09-27 |
| 3 | A page that includes another page's text (`include`, `excerpt-include`) renders it without its own version moving, so a change to the included page is not fetched | RESOLVED by R1.26 and R1.27 — it is fetched: the including page's marker moves with what it includes. Decided 2026-09-27, and read against a Data Center 9.2.21 in Docker |
| 4 | Does CQL `lastmodified` move when a file is uploaded again to a page whose version does not? If not, a windowed listing leaves the page out, and R1.18 row 2 holds only under a complete listing (R2.22, R2.24) | RESOLVED by R1.22 — it does not. A local Data Center 9.2.21 in Docker, 2026-09-27: neither a file added nor a file uploaded again moved the page's `lastmodified`, and neither did a file removed |
| 5 | Does a file or a comment on a Jira issue move its `updated`, as R1.6 row 1 needs under a windowed listing? | RESOLVED — it does. A Jira Software Data Center 10.3 in Docker, 2026-09-27: a file added, a file replaced, a file removed, a comment added and a comment edited each moved `INC-3`'s `updated`, and a windowed JQL search found it after each. Nothing needed changing |
| 6 | Should a web page's navigation, header and footer be taken out of its note? `html-markdown` keeps them, and every page of a site repeats them | RESOLVED by R8.33 — yes, by the page's own declaration: a page with one `<main>` is written as that element, without its `<nav>`. No selector to configure. Decided 2026-09-28. The note of `docs.astral.sh/uv/getting-started/installation/` went from 12,446 characters to 6,480, and `www.djangoproject.com/foundation/`'s from 17,815 to 7,800, with the article text whole in both |
| 7 | A website with no sitemap | RESOLVED by R1.37 to R1.39 — a source that says `crawl:` is listed by following its links within `url`, asking each URL once and at most `crawl:` URLs. A crawl that cannot finish fails the listing rather than tombstoning what it did not reach. The site that asked: `www.python.org`, whose listing failed on its missing sitemap. Decided 2026-09-28 |
| 8 | A website behind a credential | OPEN — `token_env` and `user_env` as R1.21 reads them would carry over. Needs a site that asks for one |
| 9 | Politeness: the requests are sequential and undelayed | RESOLVED by R1.35 and R1.36 — `djangoproject.com`, 2026-09-27: 70 of the 91 pages under `/foundation/` were answered `429` within seven seconds, with no `Retry-After`, and every one of the 70 was asked after the first refusal. A `429` now ends the sync's requests to the site, and a source's `delay:`, or its site's `Crawl-delay`, spaces them. Decided 2026-09-27 |
| 10 | A website that builds its pages with JavaScript | OPEN — the server sends a shell, and the text is drawn in the browser, so what is held has nothing in it to read. A browser is the answer that exists (crawl4ai, or Firecrawl's rendering; see the options above), and it is a second way of fetching a page, not a change to this one. Needs such a site a workspace reads |
