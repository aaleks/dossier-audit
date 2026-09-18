# 001 — Source connectors

**Status:** Implemented
**Rules:** R1.1 – R1.13

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
- **confluence** — scoped by space and optional label. Pages are exported as
  **PDF**, because the embedded images carry meaning that the storage format
  loses.

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
