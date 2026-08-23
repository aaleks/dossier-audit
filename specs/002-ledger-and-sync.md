# 002 — Ledger and incremental sync

## Purpose

Fetch only what changed, and turn mutable remote items into immutable local
snapshots that everything downstream can depend on.

## Ledger

One row per item per source.

| Column | Meaning |
|---|---|
| `source_id` | The configured source |
| `key` | Item key within that source |
| `remote_version` | Last seen server-side version marker, or `NULL` |
| `content_hash` | Hash of the **normalised** payload |
| `snapshot_path` | Content-addressed location of the stored payload |
| `first_seen` / `last_seen` | Timestamps |
| `state` | `active` or `tombstoned` |

Per source, a `last_sync_at` watermark is recorded separately.

## Sync algorithm

```
1.  since := last_sync_at - overlap        (overlap default 24h)
2.  refs  := connector.list(since)
3.  for each ref:
      a. if remote_version is present and equals the ledger row  -> skip
      b. payload := connector.fetch(ref.key)
      c. h := hash(normalise(payload))
      d. if h equals the ledger row's content_hash               -> touch only
      e. else write a new snapshot at a path derived from h,
         then update the ledger row
      f. repeat (b)-(e) independently for each attachment
4.  items in the ledger that were active but absent from a full
    listing are marked tombstoned; they are never deleted
5.  last_sync_at := start time of this sync
```

## Normalisation

Source payloads carry fields that change on every fetch — rendered HTML, view
counters, server-side timestamps, ordering of unordered collections. Hashing the
raw payload would report every item as changed on every sync.

Normalisation projects the payload onto the fields the pipeline actually
consumes, with stable key ordering, before hashing. The **stored snapshot remains
the raw payload**; normalisation exists only to compute the hash.

The set of fields is declared per source in `sources.yaml` and forms part of the
source's configuration hash.

## Must hold

**R2.1** An item whose `remote_version` is unchanged since the last sync is not
fetched.

**R2.2** An item whose normalised payload hashes to its recorded `content_hash`
does not produce a new snapshot, regardless of how many times it is fetched.

**R2.3** Changing the normalisation field list changes the source's
configuration hash and forces re-evaluation of every item in that source.

**R2.4** Sync asks for changes from `last_sync_at - overlap`, not from
`last_sync_at`. The default overlap is 24 hours and is configurable per source.

**R2.5** Re-running a sync immediately, with nothing changed remotely, fetches
zero payloads and writes zero snapshots.

**R2.6** An attachment replaced under an otherwise unchanged item is detected and
produces a new attachment snapshot.

**R2.7** An item that leaves the source's scope is tombstoned. Its snapshots
remain readable and any earlier run that referenced them still resolves.

**R2.8** A sync interrupted at any point leaves a consistent ledger: every row
present refers to a snapshot that exists and hashes to the recorded value.

**R2.9** Two syncs run against an unchanged source produce byte-identical ledger
content apart from `last_seen` and `last_sync_at`.
