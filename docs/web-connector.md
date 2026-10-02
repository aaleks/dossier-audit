# How the web connector works

A quick tour of `src/dossier/infrastructure/connectors/web.py`: what you write
to point `dossier` at a website, what a sync does, and what a
stage then reads. Written against spec 001 R1.29 – R1.43.

## Where it lives and how it is found

- Code: `src/dossier/infrastructure/connectors/web.py` (`WebConnector`). What
  it decides without the network -- which URLs a source covers, what each is
  keyed as, what a sitemap says, which links a crawl follows -- is
  `src/dossier/domain/web.py`.
- Registered in `pyproject.toml` under `dossier.connectors` as
  `web = "...web:WebConnector.from_config"`. `sources.yaml` says `type: web`.
- Left of the hash boundary, like Jira and Confluence (R0.19). `httpx` and
  `protego` are imported lazily.
- A page drawn by a browser: `src/dossier/infrastructure/connectors/browser.py`
  (`Chromium`), which imports Playwright only when a browser is opened. What a
  page being drawn may ask for is decided in `domain/web.py` (`browser_asks`).

## What you write

```yaml
# sources.yaml
sources:
  - id: vendor-docs
    type: web
    url: https://docs.example.org/ops/              # the prefix this source covers
    # sitemap: https://docs.example.org/sitemap.xml # the default: the host's own
    # crawl: 200                                    # instead of a sitemap: follow links, asking at most 200 URLs
    # render: browser                               # draw each HTML page in a headless browser
    # delay: 2                                      # seconds between requests; the default: none
```

One entry per site, and no code. Any website works that publishes a sitemap, or
links its pages to one another (`crawl:`, below), serves its pages as HTML from
the server, and lets an anonymous reader in.
Documentation sites are the case it was written against: MkDocs, Sphinx (with
`sphinx-sitemap`), Docusaurus and Read the Docs all publish a sitemap, and so
do most static site generators and content management systems.

## What a sync does

1. Reads `robots.txt` on the host once. A `4xx` allows everything; a `5xx`
   fails the sync (R1.33), and so does a `429` (R1.35, below).
2. Reads the sitemap, and every sitemap an index names on the same host
   (R1.29). Compressed sitemaps are read too.
3. Keeps each URL under `url` that `robots.txt` allows, with no query string,
   and keys it relative to `url`: `…/ops/escalation` is `escalation`,
   `…/ops/` is `index`, `…/ops/runbooks/` is `runbooks/index` (R1.30). A
   sitemap that writes its pages over `http://` for an `https://` source, as
   `www.gnu.org`'s does, still names them: each page is asked over the scheme
   `url` gives (R1.29).
4. Compares each page's `<lastmod>` with what the ledger holds, and fetches
   only the pages whose `<lastmod>` moved or that have none (R1.31, R2.1).
   A page with no `<lastmod>` is fetched each sync, and stored again only if its
   bytes changed (R2.2).
5. Stores each page as sent, labelled as its `Content-Type` says (R1.32):
   `text/html` pages go to `html-markdown`, PDFs to the PDF converters.
6. A page gone from the sitemap is tombstoned (R2.7).

A redirect is followed within `url` only, five times at most; a page that
redirects to a login form fails and names both URLs (R1.34). Within `url`
includes its scheme, so write `https://` for a site that redirects there: with
`url: http://…` every page's redirect to its `https` form is refused.

## A site with no sitemap

Some sites publish no sitemap. `www.python.org` is one: it has none, and its
`robots.txt` names none. Say `crawl:` instead, with the most URLs the crawl
may ask:

```yaml
  - id: python-community
    type: web
    url: https://www.python.org/community/
    crawl: 300
    delay: 0.5
```

Steps 2 and 3 above become a crawl (R1.37):

- **What is asked.** It starts at `url`, reads the `<a href>`s of each HTML
  page, follows each one that lies under `url`, and asks each URL once.
  `robots.txt` still keeps pages out.
- **Keys.** A page is keyed by the URL it was answered at, so `…/sigs` that
  redirects to `…/sigs/` is one page, `sigs/index`.
- **What is passed over.** A link answered `404` is not a page, and neither is
  one that redirects out of `url`. The crawl passes over them and goes on.
- **One request per page per sync.** The crawl has already downloaded every
  page, so `fetch` hands back those bytes and asks nothing. No page has a
  marker, so each is compared by its bytes and stored again only if they
  changed.

**When the crawl fails instead of listing (R1.38).** A crawled listing is
complete, and anything held that it does not name is tombstoned, so a crawl that
cannot finish lists nothing:

- `url` is not a page, or `robots.txt` disallows it;
- a page answers `5xx` or `429`, or does not answer;
- a page redirects more than five times;
- there is one more URL to ask after `crawl:` URLs have been asked.

The last failure names the URL that was left, and the fix is a larger `crawl:`.
There is no default: how many pages a site has is yours to say (R1.39).

Measured on 2026-09-28:

- `www.python.org/community/` with `crawl: 300` and `delay: 0.5` listed 69
  pages in 70 seconds. Along the way it passed over 14 broken links and followed
  51 redirects from a URL without its slash to one with it. A second sync wrote
  nothing.
- `crawl: 5` on `www.python.org/about/`, which has 7 pages, failed naming
  `…/about/legal/`.
- Crawled, `docs.astral.sh/uv` lists the same 84 pages its sitemap names, in
  about 20 seconds. A sitemap is still the better listing where there is one:
  it costs one request, and its `<lastmod>` spares every unchanged page.

## When a site says slow down

A site that answers `429 Too Many Requests` is asked nothing more that sync
(R1.35). The page it refused fails, and so does every page after it, without a
request; each is owed to the next sync (R2.23), and `dossier sync` lists them.

Stopping keeps `dossier` polite, and it is not enough on its own. A page with no
`<lastmod>` is fetched every sync, in key order, so a site that allows twenty
requests at a time is spent on the same twenty pages every sync. Ask it more
slowly: `delay: 2` starts each request at least two seconds after the last
(R1.36). A `Crawl-delay` in the site's `robots.txt` is honoured on its own, and
`delay:` can lengthen it but never shorten it. With neither, requests go back to
back, which is what a documentation site behind a CDN is happy with:
`docs.astral.sh/uv` lists 84 pages and syncs them in 12 to 20 seconds.

`djangoproject.com` is the site that asked for this: 70 of the 91 pages under
`/foundation/` were answered `429` within seven seconds, with no `Retry-After`.
With `delay: 1`, one sync held all 91, in 92 seconds.

## What a stage reads

A page is stored as the site sent it, with its header, menus and footer, and
`html-markdown` decides what goes into the note (spec 008). If the page declares
one `<main>` -- HTML's element for "the dominant contents of the document", or
`role="main"` -- the note is that element, without any `<nav>` inside it
(R8.33). So the site's name, its search box, its menus, a documentation theme's
sidebars and the footer are not in it. A page with no `<main>`, or with two, is
written whole. Nothing is chosen by class name or by how much text a block has,
so no paragraph is dropped by a guess.

Measured on 2026-09-28, notes shrank by about half:
`docs.astral.sh/uv/getting-started/installation/` went from 12,446 characters to
6,480, and `www.djangoproject.com/foundation/` from 17,815 to 7,800. The article
text is whole in both.

## A page drawn in the browser

Some sites send a page as a script that writes it. What the server sends is a
shell, and the text is drawn in the browser. `html-markdown` takes scripts out,
so the note of such a page is empty. Say `render: browser`, and each HTML page is
held as a headless Chromium draws it (R1.40):

```yaml
  - id: quotes
    type: web
    url: https://quotes.toscrape.com/js/
    crawl: 30
    render: browser
```

It needs the extra and its browser, once:

```bash
pip install dossier[browser]
playwright install chromium-headless-shell   # about 115 MB
```

What happens to each page:

- **Asking.** `dossier` asks for the page as it asks for every page, so
  `robots.txt`, redirects, `429` and `delay:` hold.
- **Drawing.** If the answer is HTML, `dossier` hands those bytes to the
  browser, which does not ask for the page again. It runs the page's scripts,
  and when no request has been open for half a second, the page is held as the
  browser holds it.
- **Encoding.** A drawn page is stored as UTF-8 behind a byte-order mark, so
  `html-markdown` reads it as drawn, whatever charset the page declared.
- **With `crawl:`**, links are read from the drawn page.

Every request the page's scripts make comes back to the connector first (R1.41):

- **Not asked for:** images, fonts, video, audio, another frame's page, and
  anything but `GET`. A script that moves the browser to a login form is not
  followed.
- **Requests to the site** go the way every request to it goes. `robots.txt`
  may keep them out, `delay:` spaces them, a `429` fails the page and stops the
  sync's requests, and a script or stylesheet is asked once a sync.
- **Requests to other hosts** (a CDN, an API) are sent by the browser itself.

A page that has not gone quiet within sixty seconds fails; half a page is not
held. A PDF, or anything else that is not HTML, is stored as sent, and no browser
sees it. A site that routes its pages by fragment (`…/#/escalation`) is one page
to `dossier`, because a fragment is not part of an address (R1.30).

Measured on 2026-09-28, `quotes.toscrape.com/js/`, a site built to be read this
way, with `crawl: 30`:

| | Pages | First sync | Second sync | What the note of `index` holds |
|---|---|---|---|---|
| without `render:` | 11 | 6.7 s | 6.2 s, nothing stored | the site's name, `Login`, `Next →`, and no quote |
| `render: browser` | 11 | 19.3 s | 18.9 s, nothing stored | every quote on the page, with its author and tags |

Draw only the sites that need it. `docs.astral.sh/uv`, which needs no browser,
took 217 seconds drawn against 12 to 20 read as sent. From a sitemap, a browser
is started for each page fetched; a crawl starts one for all of its pages. And
the site's theme rewrites every in-page link as an absolute URL when its scripts
run, so the note of `getting-started/installation/` grew from 6,480 characters
to 7,751 without a word more of text.

## Try it

`playground/18-a-website-read-as-documents` reads uv's documentation, part of
`www.python.org` and `quotes.toscrape.com` with each of the above, from the
command line, and says what to look for at each step.

## What it does not do yet

- Send a credential (open question 8).
