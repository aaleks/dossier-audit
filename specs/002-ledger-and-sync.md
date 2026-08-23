# 002 — Ledger and incremental sync

**Status:** Proposed
**Rules:** R2.1 – R2.9

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

### R2.1 — an item whose remote version is unchanged is not fetched

Where the source offers a version marker, it is trusted and the payload is never
requested.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.needs_fetch`)
- **Proved by:** `tests/unit/test_R002_1__unchanged_remote_version_is_not_fetched.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | ledger row `OPS-114` at `v37`, listing reports `v37` | no fetch |
| 2 | ledger row `OPS-114` at `v37`, listing reports `v38` | fetch |
| 3 | no ledger row for `INC-4901`, listing reports `2026-08-06T08:41:00Z` | fetch; an unknown item is always fetched |
| 4 | *counter-example* — `audit-note.pdf`, whose `remote_version` is `None` | the rule does not apply; change detection falls through to payload hashing (R2.2) |

### R2.2 — an unchanged normalised payload produces no new snapshot

Re-fetching is cheap and sometimes unavoidable. Re-storing is not, and a second
snapshot of identical content would make the store lie about what changed.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.classify`)
- **Proved by:** `tests/unit/test_R002_2__identical_payload_writes_no_new_snapshot.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `audit-note.pdf` fetched, normalised hash `c4a70b93`, ledger already `c4a70b93` | no snapshot written; `last_seen` updated |
| 2 | the same file fetched five times in one sync | one hash computation per fetch, zero snapshots written |
| 3 | `INC-4822` fetched, normalised hash `77c1b40a`, ledger holds `0e52dd18` | a new snapshot at `77c1b40a`; the ledger row is repointed |
| 4 | *counter-example* — the raw payload differs only in a field excluded by the normalisation projection | no new snapshot; that is precisely what normalisation is for |

### R2.3 — changing the normalisation field list re-evaluates every item in that source

The projection is part of the source's configuration hash, because a different
projection means the recorded hashes answer a different question.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.source_config_hash`)
- **Proved by:** `tests/unit/test_R002_3__normalisation_change_forces_reevaluation.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `fields` gains `comments` | the source configuration hash changes; every item in `incidents-jira` is re-fetched and re-hashed |
| 2 | `fields` reordered from `[key, summary]` to `[summary, key]` | the hash does **not** change; the projection is a set, ordered canonically before hashing |
| 3 | `fields` loses `description` | the configuration hash changes; re-evaluation follows |
| 4 | *counter-example* — `watermark_overlap` changed from `24h` to `48h` | no configuration hash change; the overlap affects what is asked for, never what a payload hashes to |

### R2.4 — sync asks from `last_sync_at` minus an overlap, never from `last_sync_at`

Clock skew between dossier and the source, plus source-side indexing lag, will
otherwise drop items silently. The default overlap is 24 hours, configurable per
source.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.window_start`)
- **Proved by:** `tests/unit/test_R002_4__watermark_overlap_refetches_boundary_items.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `last_sync_at=2026-08-06T09:00:00Z`, default overlap | `since = 2026-08-05T09:00:00Z` |
| 2 | the same watermark, `watermark_overlap: 48h` | `since = 2026-08-04T09:00:00Z` |
| 3 | an item indexed late, changed at `2026-08-05T16:02:00Z` but invisible at the previous sync | inside the window, and picked up |
| 4 | *counter-example* — a source that has never synced, `last_sync_at` is `NULL` | `since = None`; the overlap has nothing to subtract from and a full listing is requested |

### R2.5 — a second sync with nothing changed fetches zero payloads and writes zero snapshots

The observable promise of incremental sync. It is also the cheapest end-to-end
proof that the ledger, the hashing and the store agree with each other.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync`)
- **Proved by:** `tests/acceptance/test_R002_5__second_sync_fetches_nothing.py`
- **Status:** IN PROGRESS

| # | Given | Then |
|---|-------|------|
| 1 | `dossier sync` run twice over `tests/fixtures/inbox/incidents/`, unchanged between runs | the second run reports `0 fetched`, `0 new snapshots`, `0 tombstoned` |
| 2 | the snapshot store after the second run | byte-identical to its state after the first |
| 3 | the ledger after the second run | identical apart from `last_seen` and `last_sync_at` (R2.9) |
| 4 | *counter-example* — one fixture file edited between the two runs | that one item is fetched and snapshotted; the others still report no work |

### R2.6 — a replaced attachment is detected under an otherwise unchanged item

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.classify`)
- **Proved by:** `tests/unit/test_R002_6__replaced_attachment_is_detected.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` at `v37` unchanged, its attachment `report.pdf` replaced | a new attachment snapshot; the item's own snapshot is untouched |
| 2 | the same, and the pipeline consumes that attachment | the documents derived from it re-convert and the stages re-run (R5.7) |
| 3 | an attachment removed from `INC-4821` | the attachment row is tombstoned; the item row stays `active` |
| 4 | *counter-example* — an attachment renamed, with identical bytes | the same content hash; no new snapshot, only the ledger's key changes |

### R2.7 — an item leaving scope is tombstoned, and its snapshots stay resolvable

A run from March must still resolve the documents it used.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.tombstones`)
- **Proved by:** `tests/unit/test_R002_7__out_of_scope_items_are_tombstoned_not_deleted.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` active in the ledger, absent from a full listing | `state=tombstoned`; the row and the snapshot at `a3f9c1e2` both remain |
| 2 | a run pinned to `a3f9c1e2`, replayed after that tombstoning | resolves and reproduces byte-for-byte (R4.7) |
| 3 | `INC-4821` returning to scope at a later sync | the same row goes back to `active`; `first_seen` is not rewritten |
| 4 | *counter-example* — an incremental listing with `since` set, which `INC-4821` is legitimately absent from | nothing is tombstoned; tombstoning is computed only against a full listing (R1.3) |

### R2.8 — an interrupted sync leaves a consistent ledger

Every row present refers to a snapshot that exists and hashes to the recorded
value. The failure mode this rules out is a ledger claiming content the store
does not hold, which turns into an unresolvable run months later.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync`)
- **Proved by:** `tests/unit/test_R002_8__interrupted_sync_leaves_a_consistent_ledger.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | the process is killed between writing the snapshot and updating the row | the row still holds the previous hash; the orphan snapshot is unreferenced and inert |
| 2 | the process is killed mid-write of a snapshot | no ledger row refers to the partial file; it is never treated as content |
| 3 | a sync resumed after either interruption | completes; the interrupted item is re-fetched and committed normally |
| 4 | *counter-example* — `last_sync_at` after an interrupted sync | not advanced; a partial sync must not be mistaken for a complete one |

### R2.9 — two syncs over an unchanged source produce byte-identical ledger content

Apart from `last_seen` and `last_sync_at`, which are the only fields that record
when rather than what.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync`)
- **Proved by:** `tests/unit/test_R002_9__repeated_sync_is_byte_identical.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | two syncs of `incidents-manual`, nothing changed | ledger rows identical apart from `last_seen` |
| 2 | the same, with the ledger serialised for comparison | identical bytes once the two time columns are excluded |
| 3 | the two syncs run under different locales and timezones | still identical; no locale-formatted value is stored (R0.4) |
| 4 | *counter-example* — `first_seen` on a row created by the first sync | set once and never rewritten, so it is identical by definition rather than by exclusion |
