# How the web connector works

A quick tour of `src/dossier/infrastructure/connectors/web.py`: what you write
to point `dossier` at a documentation website, what a sync does, and what a
stage then reads. Written against spec 001 R1.23 – R1.28.

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

One entry per site, and no code. MkDocs, Sphinx (with `sphinx-sitemap`),
Docusaurus, Read the Docs and most static site generators publish a sitemap.

## What a sync does

1. Reads `robots.txt` on the host once. A `4xx` allows everything; a `5xx`
   fails the sync (R1.27).
2. Reads the sitemap, and every sitemap an index names on the same host
   (R1.23). Compressed sitemaps are read too.
3. Keeps each URL under `url` that `robots.txt` allows, with no query string,
   and keys it relative to `url`: `…/ops/escalation` is `escalation`,
   `…/ops/` is `index`, `…/ops/runbooks/` is `runbooks/index` (R1.24).
4. Compares each page's `<lastmod>` with what the ledger holds, and fetches
   only the pages whose `<lastmod>` moved or that have none (R1.25, R2.1).
   A page with no `<lastmod>` is fetched each sync, and stored again only if its
   bytes changed (R2.2).
5. Stores each page as sent, labelled as its `Content-Type` says (R1.26):
   `text/html` pages go to `html-markdown`, PDFs to the PDF converters.
6. A page gone from the sitemap is tombstoned (R2.7).

A redirect is followed within `url` only, five times at most; a page that
redirects to a login form fails and names both URLs (R1.28).

## What it does not do yet

- Take out navigation, headers and footers. `html-markdown` keeps what the page
  shows, chrome included (spec 001, open question 5).
- Read a site with no sitemap (open question 6).
- Send a credential (open question 7).
- Pace its requests (open question 8).
