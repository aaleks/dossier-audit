# How the Jira connector works

A quick tour of `src/dossier/infrastructure/connectors/jira.py`, what you
have to write to point it at your Jira, and what a sync actually does. Written
against branch `jira-dotenv-cloud-basic` (R1.8 rows 5-6, R1.12, R1.13).

## Where it lives and how it is found

- Code: `src/dossier/infrastructure/connectors/jira.py` (`JiraConnector`).
- Registered in `pyproject.toml` under the `dossier.connectors` entry-point
  group as `jira = "...jira:JiraConnector.from_config"`. `sources.yaml` says
  `type: jira` and the registry (`connectors/registry.py`) resolves that name
  to the factory. Nothing in `dossier` dispatches on the string `"jira"` (R1.7).
- It is left of the hash boundary: one of the three packages allowed to touch
  the network (R0.10). `httpx` is imported lazily inside `_get`, so a command
  that never builds the connector never pays for it.

## What you write

Two files. `sources.yaml` says *where* and *what*; `.env` says *with which
credential*. Nothing in `sources.yaml` is ever interpolated — no `${...}`, no
`$env:` — because `token_env` already *is* the reference: it names the
variable, and `dossier.config` reads the variable.

```yaml
# sources.yaml
sources:
  - id: incidents-jira
    type: jira
    url: https://jira.example.internal        # base URL, no trailing /rest
    query: project = INC AND type = Incident
    token_env: DOSSIER_JIRA_TOKEN             # the NAME of the variable, never the value
    # user_env: DOSSIER_JIRA_USER             # name this too for HTTP Basic (R1.12)
    # deployment: cloud                       # absent = datacenter (R1.13)
    fields: [key, summary, status, created, resolution, description]   # optional
    watermark_overlap: 24h                    # optional, shared by every source type
```

```dotenv
# .env  (git-ignored; copy from .env.example)
DOSSIER_JIRA_TOKEN=xxxx
# DOSSIER_JIRA_USER=you@example.com
```

The variable is named with the `DOSSIER_` prefix because `.env` yields only
`DOSSIER_` variables (R9.11 row 4). `JIRA_TOKEN=…` written only in `.env` is
invisible to dossier and refused by name when the connector is built (R1.8
row 6). A variable set in the shell wins over `.env`, as for every other value.

The keys, checked at load time against `JiraKeys` (R1.10):

| Key | Owner | Required | Meaning |
|---|---|---|---|
| `url` | jira | yes | base of the Jira instance; `/rest/api/2/...` is appended |
| `query` | jira | yes | the JQL that scopes the source |
| `token_env` | jira | no | variable holding the token; alone → `Authorization: Bearer` |
| `user_env` | jira | no | variable holding the user; with `token_env` → `Authorization: Basic user:token`. Without `token_env` it is refused at load time |
| `deployment` | jira | no | `datacenter` (default) or `cloud`; picks the listing route |
| `fields` | core | no | projection the content hash is taken over (R2.10); the raw payload is still what gets stored (R2.17) |
| `convert` | core | no | which converters run on the held documents |
| `watermark_overlap` | core | no | how far before the last sync to ask from (R2.4, default 24h) |

`JiraKeys` is `extra="forbid"`, so any other key is a load-time error naming
the line. Writing `token:` (or `password`, `api_key`, ...) is refused outright,
because `sources.yaml` is committed (R1.8 row 1).

Then a pipeline names the source, `pipelines/<name>/pipeline.yaml`:

```yaml
sources: [incidents-jira]
```

and `dossier sync <name>` syncs it (`dossier sync <name> --full` for an
unwindowed listing, R2.22).

## Which auth, for which Jira

| Your Jira | Credential | `sources.yaml` | Header sent |
|---|---|---|---|
| Data Center / Server, personal access token | the PAT | `token_env` only | `Bearer <pat>` |
| Data Center / Server, username + password | the password | `token_env` + `user_env` | `Basic base64(user:password)` |
| Cloud, API token | the API token | `token_env` + `user_env` (your Atlassian email) + `deployment: cloud` | `Basic base64(email:token)` |

The scheme is decided once, from the keys. There is no probe-and-fall-back: a
401 is reported with the URL and the status, and the token is not sent a second
time in the other form (R1.12 row 4). Neither key → no `Authorization` header,
for a Jira open to anonymous reads.

## The credential path

`dossier sync` builds the connector like this (`cli/main.py`):

```python
connector = build_connector(
    source,
    workspace=workspace,
    credential=credential_for(source, environ=environment(workspace)),
)
```

`environment(workspace)` is the shell with `.env` beneath it (R9.11).
`credential_for` (`config/credentials.py`) reads the variables named by
`token_env` and `user_env` and hands a `Credential` to the connector; the
connector never looks at `os.environ` itself (R1.8). The token and the user
never appear in a log line, error, ledger row or manifest: `Credential`'s
`repr`/`str` print `<credential from DOSSIER_JIRA_TOKEN>`, and
`JiraRequestFailed` names the URL and status only.

The credential is asked for when the connector is built, not at load time
(R3.8): `dossier plan` over a Jira source works on a machine with no token;
only `sync` needs it. A named variable that is unset or empty → exit 2 with
`CredentialUnset`, before any request.

## What a sync actually does

Every request is a `GET`; there is no other verb on the class (R1.1). Timeout
60 s. `Accept: application/json` plus the `Authorization` above on each one.

```
dossier sync <pipeline>
  └─ for each source the pipeline names
       └─ JiraConnector.list(since)
            jql = "<query> AND updated >= '<since - overlap - 1 day>'"   (R1.4)
            fields = updated,attachment, 50 per page
            datacenter: GET /rest/api/2/search      startAt=0,50,… until total   (R1.13 row 1)
            cloud:      GET /rest/api/2/search/jql  nextPageToken=… until isLast (R1.13 row 2)
            → ItemRef(key="INC-4821", remote_version="<updated>", updated_at=...)
          for each issue
            ├─ connector.attachments(key)         GET /rest/api/2/issue/INC-4821?fields=attachment
            │    → AttachmentRef(key="INC-4821/report.pdf", remote_version="<attachment id>")
            ├─ if the version marker moved (or no marker): fetch the issue
            │    connector.fetch("INC-4821")      GET /rest/api/2/issue/INC-4821?expand=names,schema   (R1.28)
            │    → RawItem(payload=<bytes as Jira sent them>, media_type=application/vnd.dossier.jira-issue+json)
            └─ for each attachment whose id moved: fetch the file
                 connector.fetch("INC-4821/report.pdf")   GET <attachment.content URL>
                 → RawItem(payload=<file bytes>, media_type=<Jira's mimeType, else Content-Type>)
```

Points the code makes deliberately:

- **An issue and its files are separate addresses** (R1.6). `INC-4821` is the
  issue JSON; `INC-4821/report.pdf` is the file. Each has its own ledger row,
  snapshot and version marker. The issue's marker is Jira's `updated`; the
  file's marker is Jira's attachment id, which changes exactly when the bytes
  do. So a replaced attachment under an untouched issue is detected on its own
  (R2.6), and a removed one is tombstoned on its own.
- **Payloads are stored byte for byte** (R1.2). The issue JSON is not
  re-serialised; the content hash is stable across runs for that reason. If
  `fields:` is set, the hash is taken over that projection but the raw payload
  is what is held (R2.17).
- **The `since` window is widened on purpose** (R1.4). Jira reads a bare
  `updated >= "..."` in the server's timezone, which the client cannot know, so
  `domain.sync.server_zone_floor` subtracts a day on top of `watermark_overlap`.
  Over-listing costs a version comparison; under-listing is a stale document
  nobody sees.
- **A windowed listing is not complete** (R1.11). The connector declares
  `lists_everything = False`, so sync only subtracts held-from-listed to
  tombstone against a listing it asked for with no window (`--full`, R2.21,
  R2.22).
- **A file or a comment moves the issue's `updated`.** A Jira Software Data
  Center 10.3 in Docker showed it on 2026-09-27: a file added, replaced or
  removed, and a comment added or edited, each moved `updated`, and a windowed
  search found the issue each time (spec 001 Q5). So a windowed listing misses
  none of them, unlike Confluence's (R1.22).
- **An issue is fetched with its field names and types** (R1.28). A custom field
  is `customfield_10050` in `fields`; `expand=names,schema` says it is `Root
  cause`, of type `string`. The note writes each one a person reads under that
  name (R8.31), and leaves out Jira Software's own machinery, typed `any`.
  The listing asks for none of it. Since the fetch asks for more than it did,
  every held issue is fetched again, once, after an upgrade (R2.26).
- **A missing `updated` is `None`, never a fetch time** (R1.5). A fabricated
  marker would make R2.1 skip a real change.
- **Media type comes from Jira, not the filename** (R2.16, R8.3).
  `reported_media_type(mimeType, Content-Type)` in the domain decides which wins.
- **A failed fetch leaves that item's ledger row untouched** (R1.9); the sync
  reports it under the source line and exits non-zero.

## Tests that pin the behaviour above

`tests/unit/test_R001_1__…` through `test_R001_13__…` for the connector and
its keys; `test_R001_8__…` for credentials, including the two `.env` cases
driven through `dossier sync`; `test_R002_6__…` and `test_R002_17__…` for
attachments and raw snapshots. All run against an `httpx` mock transport;
nothing in the default suite reaches a network.
