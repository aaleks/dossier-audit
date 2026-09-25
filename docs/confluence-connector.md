# How the Confluence connector works

A quick tour of `src/dossier/infrastructure/connectors/confluence.py` and the
converter that reads what it holds: what you write to point it at a Confluence,
what a sync does, and what a stage then reads. Written against spec 001 R1.15 –
R1.21 and spec 008 R8.19 – R8.20, and checked against two real Confluence Data
Center servers (`cwiki.apache.org`, 9.2.21, and `confluence.atlassian.com`).

## Where it lives and how it is found

- Code: `src/dossier/infrastructure/connectors/confluence.py`
  (`ConfluenceConnector`), with the header decision shared with Jira in
  `connectors/atlassian.py`, and the export's marker in
  `domain/confluence.py`.
- Registered in `pyproject.toml` under `dossier.connectors` as
  `confluence = "...confluence:ConfluenceConnector.from_config"`. `sources.yaml`
  says `type: confluence`, and the registry resolves the name (R1.7).
- The converter, `confluence-page-markdown`, is
  `src/dossier/infrastructure/converters/confluence_page_markdown.py`. The note
  it writes is decided in `domain/confluence_page.py`. Both ship in the core
  install, like the connector.
- Left of the hash boundary, like Jira (R0.10). `httpx` is imported lazily.

## What you write

```yaml
# sources.yaml
sources:
  - id: procedures-confluence
    type: confluence
    url: https://confluence.example.internal   # base, including any context path (/confluence)
    query: space = OPS AND label = procedure   # CQL; `AND type = page` is added for you
    token_env: DOSSIER_CONFLUENCE_TOKEN        # the NAME of the variable, never the value
    # user_env: DOSSIER_CONFLUENCE_USER        # name this too for HTTP Basic (R1.21)
    # export: pdf                              # also hold each page's PDF export (R1.19)
```

A CQL query containing `:` or `"` must be quoted as a whole in YAML:
`query: 'space = KAFKA AND title = "KIP-1368: Client framework name and version"'`.

The keys, checked at load time against `ConfluenceKeys` (R1.10):

| Key | Required | Meaning |
|---|---|---|
| `url` | yes | base of the Confluence instance; `/rest/api/content/...` is appended |
| `query` | yes | the CQL that scopes the source: a space, a label, a page tree (`ancestor = 81920100`), a title |
| `token_env` | no | variable holding the token; alone → `Authorization: Bearer` |
| `user_env` | no | variable holding the user; with `token_env` → `Authorization: Basic user:token`; without it → refused at load time |
| `export` | no | `pdf`, or absent. Any other value is refused at load time |

`fields`, `convert` and `watermark_overlap` are the core's, as for every source.
Authentication is decided exactly as for Jira, by one shared function: a
personal access token alone on Data Center, an email and API token on Cloud,
neither for a Confluence open to anonymous readers (R1.21). The credential path
is the Jira guide's: `credential_for` reads the named variables, and the
connector never looks at the environment (R1.8).

## What a sync actually does

Every request is a `GET` (R1.1). Timeout 60 s.

```
dossier sync <pipeline>
  └─ ConfluenceConnector.list(since)
       cql = "(<query>) AND type = page [AND lastmodified >= '<since - 1 day>']"   (R1.15, R1.4)
       GET /rest/api/content/search?cql=…&expand=version   start=0,50,… until no _links.next
       → ItemRef(key="81920114", remote_version="v37", updated_at=<version.when>)   (R1.16)
     for each page
       ├─ connector.attachments("81920114")
       │    GET /rest/api/content/81920114/child/attachment?expand=version   (paged)
       │    → AttachmentRef(key="81920114/escalation-matrix.png", remote_version="81920301:v2")   (R1.18)
       │    with export: pdf, also
       │    → AttachmentRef(key="81920114.pdf", remote_version="v37+<12 hex>")   (R1.19)
       ├─ if the page's marker moved: fetch it
       │    GET /rest/api/content/81920114?expand=body.export_view,version,space
       │    → RawItem(payload=<bytes as sent>, media_type=application/vnd.dossier.confluence-page+json)   (R1.17)
       ├─ for each file whose marker moved
       │    GET <url><_links.download>        → media type as Confluence records it (R2.16)
       └─ for the export, if its marker moved
            GET /spaces/flyingpdf/pdfpageexport.action?pageId=81920114
                X-Atlassian-Token: no-check   → 302 → /download/export/….pdf, same session
            → RawItem(payload=<PDF>, media_type=application/pdf)
```

Points the code makes deliberately:

- **A page is keyed by its id, never its title** (R1.16). A rename is an edit,
  not a tombstone and a new item. The note carries the title.
- **The page is fetched rendered, not in storage format** (R1.17). Storage holds
  `<ac:structured-macro>` elements only Confluence can draw; `export_view` is the
  page a reader sees.
- **A file's marker is its attachment id and version** (R1.18). Uploading again
  under the same name keeps the id and raises the version; deleting and
  uploading again makes a new id at version 1. Either alone misses a case.
- **The export's marker includes its files'** (R1.19). An image replaced in
  place leaves the page at its version, and changes the PDF, which draws it.
- **A refused export is a failure, not a skip** (R1.20). `export: pdf` says the
  server exports. A `401` or `403` fails `<page id>.pdf` with a message naming
  both fixes; anything not starting with `%PDF-` (a login page, say) fails
  naming the type it came as. The page and its files are still held, and the
  watermark stays put, so the next sync reports it again.
- **Payloads are stored byte for byte** (R1.2), and a rendered page is not the
  same bytes twice: the table of contents is drawn with a class holding the
  render time. An unchanged marker is never fetched, so this matters only when
  `fields:` changes and every page is fetched again (R2.3). The note is the same
  either way, so a stage reading it is served from cache.

## What a stage reads

`confluence-page-markdown` writes a note like this (R8.19, R8.20):

```markdown
# OPS-114 Incident escalation procedure

**Space:** OPS
**Version:** 37
**Updated:** 2026-08-05T16:02:00.000Z
**By:** m.keller

## Escalation

- Page the incident commander within 15 minutes.
- Open a bridge and post its link in the incident channel.

Who is on call is in [the rota](https://status.example/rota). Pool lb_acq_01 alerts page the payments team.

![escalation-matrix.png](escalation-matrix.png)
```

- The body goes through `markdownify` with nothing escaped, so `lb_acq_01` and
  `3*2` are quoted as they stand.
- The table of contents, `<style>` and `<script>` are taken out first.
- Text inside an expand macro is kept: a reader can open it.
- An image is its file's name. The file is its own document, converted as an
  image is (R8.10). The server's URL is not kept.
- `_links`, `_expandable`, user keys and the version message are in the payload
  and not in the note, so a model cannot find a quote in them.

The PDF export converts to `markdown` by default, like any PDF (R8.10). A
source's `convert:` applies to every document it holds, so asking for
`page_images` asks it of the page JSON too, which nothing claims (R8.5); that is
spec 008's open question 5.

## What it does not do yet

These are spec 001's open questions:

- **Confluence Cloud** is not verified. Its version-1 content routes answer
  under `/wiki`, but its PDF export is an asynchronous task.
- **Page comments** are not part of the page's document.
- **A page that includes another page** renders that page's text without its
  own version moving, so a change to the included page is not fetched.

## Tests that pin the behaviour above

`tests/unit/test_R001_15__…` through `test_R001_21__…` for the connector,
`test_R008_19__…` and `test_R008_20__…` for the note, and
`tests/acceptance/test_R008_19__a_confluence_page_is_audited_end_to_end.py`,
which syncs, converts and audits a page through the CLI. The fixtures in
`tests/fixtures/confluence/` have the shape Confluence 9.2.21 sends, with the
fixtures' own content. Everything runs against an `httpx` mock transport.
