# How the web connector works

A quick tour of `src/dossier/infrastructure/connectors/web.py`: what you write
to point `dossier` at a website, what a sync does, and what a
stage then reads. Written against spec 001 R1.29 – R1.34.

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
```

One entry per site, and no code. Any website works that publishes a sitemap,
serves its pages as HTML from the server, and lets an anonymous reader in.
Documentation sites are the case it was written against: MkDocs, Sphinx (with
`sphinx-sitemap`), Docusaurus and Read the Docs all publish a sitemap, and so
do most static site generators and content management systems.

## What a sync does

1. Reads `robots.txt` on the host once. A `4xx` allows everything; a `5xx`
   fails the sync (R1.33).
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

## What it does not do yet

- Take out navigation, headers and footers. `html-markdown` keeps what the page
  shows, chrome included (spec 001, open question 6).
- Read a site with no sitemap (open question 7).
- Send a credential (open question 8).
- Pace its requests (open question 9).
- Read a page the browser builds with JavaScript: it holds the empty shell the
  server sends (open question 10).
