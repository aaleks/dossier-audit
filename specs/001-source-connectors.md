# 001 — Source connectors

## Purpose

Define the single interface every source type implements, so that adding a new
source system requires no change to the ledger, the store, the cache or any
pipeline.

## Interface

A connector implements exactly three operations.

```python
class Connector(Protocol):
    def list(self, since: datetime | None) -> Iterator[ItemRef]:
        """Every item currently in scope. When `since` is given, the connector
        MAY restrict the result to items changed at or after it. Returning more
        than asked for is always allowed; returning less is not."""

    def fetch(self, key: str) -> RawItem:
        """The full payload of one item."""

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
```

## Registration

Connectors are discovered through the `dossier.connectors` entry point group.
A new source type is a package that declares one; it is never added to a match
statement inside `dossier`.

```toml
[project.entry-points."dossier.connectors"]
jira = "dossier_jira:JiraConnector"
```

## Connector types in scope

- **folder** — a local directory. `remote_version` is always `None`; change
  detection falls back to payload hashing (spec 002).
- **jira** — scoped by a JQL query. Issue fields as JSON, attachments separate.
- **confluence** — scoped by space and optional label. Pages are exported as
  **PDF**, because the embedded images carry meaning that the storage format
  loses.

## Must hold

**R1.1** A connector performs no writes against the source system.

**R1.2** `fetch` returns the payload byte-for-byte as received. Any normalisation
happens later, in the ledger layer, and never mutates the stored snapshot.

**R1.3** `list(since=None)` returns every item currently in scope.

**R1.4** `list(since=t)` returns a superset of the items whose true change time
is at or after `t`. Returning extra items is correct; omitting one is a defect.

**R1.5** A connector that cannot supply `remote_version` sets it to `None` rather
than fabricating one.

**R1.6** Attachments are addressable and versioned independently of the item that
carries them.

**R1.7** Adding a new connector requires no edit to any file in the `dossier`
core package.

**R1.8** Credentials are read from the environment or a secret store, never from
`sources.yaml`, and never appear in a log line, a ledger row or a manifest.

**R1.9** A connector raising a network error leaves the ledger unchanged for that
item. Partial sync must never record an item it did not successfully store.
