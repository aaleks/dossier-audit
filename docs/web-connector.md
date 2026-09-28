# How the web connector works

A quick tour of `src/dossier/infrastructure/connectors/web.py`: what you write
to point `dossier` at a website, what a sync does, and what a
stage then reads. Written against spec 001 R1.29 – R1.36.

## Where it lives and how it is found

- Code: `src/dossier/infrastructure/connectors/web.py` (`WebConnector`). What
  it decides without the network -- which URLs a source covers, what each is
  keyed as, what a sitemap says -- is `src/dossier/domain/web.py`.
- Registered in `pyproject.toml` under `dossier.connectors` as
  `web = "...web:WebConnector.from_config"`. `sources.yaml` says `type: web`.
- Left of the hash boundary, like Jira and Confluence (R0.10). `httpx` and
  `protego` are imported lazily.

## What you write

```yaml
# sources.yaml
sources:
  - id: vendor-docs
    type: web
    url: https://docs.example.org/ops/              # the prefix this source covers
    # sitemap: https://docs.example.org/sitemap.xml # the default: the host's own
    # delay: 2                                      # seconds between requests; the default: none
```

One entry per site, and no code. Any website works that publishes a sitemap,
serves its pages as HTML from the server, and lets an anonymous reader in.
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
   `…/ops/` is `index`, `…/ops/runbooks/` is `runbooks/index` (R1.30).
4. Compares each page's `<lastmod>` with what the ledger holds, and fetches
   only the pages whose `<lastmod>` moved or that have none (R1.31, R2.1).
   A page with no `<lastmod>` is fetched each sync, and stored again only if its
   bytes changed (R2.2).
5. Stores each page as sent, labelled as its `Content-Type` says (R1.32):
   `text/html` pages go to `html-markdown`, PDFs to the PDF converters.
6. A page gone from the sitemap is tombstoned (R2.7).

A redirect is followed within `url` only, five times at most; a page that
redirects to a login form fails and names both URLs (R1.34).

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

## What it does not do yet

- Read a site with no sitemap (open question 7).
- Send a credential (open question 8).
- Read a page the browser builds with JavaScript: it holds the empty shell the
  server sends (open question 10).
