# 001 — Source connectors

**Status:** Partially implemented
**Rules:** R1.1 – R1.10

## Purpose

Define the single interface every source type implements, so that adding a new
source system requires no change to the ledger, the store, the cache or any
pipeline.

Connectors are the only code left of the hash boundary (R0.1). Everything a
connector does is therefore assumed to be unrepeatable, and everything after it
is assumed not to be.

## Interface

A connector implements exactly three operations.

```python
class Connector(Protocol):
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
- **Status:** NOT MET

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
- **Status:** NOT MET

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

- **Kind:** deterministic
- **Layer:** config (`dossier.config.credentials`)
- **Proved by:** `tests/unit/test_R001_8__credentials_never_reach_config_or_logs.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `sources.yaml` containing a `token:` key | load-time error naming the file and the key |
| 2 | `JIRA_TOKEN` set and a sync failing with an HTTP 401 | the error message contains the URL and the status, and not the token |
| 3 | a completed sync of `incidents-jira` | no ledger column and no manifest field holds the token |
| 4 | *counter-example* — the name `JIRA_TOKEN` appearing in `sources.yaml` as `token_env: JIRA_TOKEN` | allowed; naming the variable is not disclosing its value |

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
