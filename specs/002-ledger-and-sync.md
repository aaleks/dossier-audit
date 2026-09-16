# 002 — Ledger and incremental sync

**Status:** Partially implemented
**Rules:** R2.1 – R2.17

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
| `snapshot_path` | Content-addressed location of the stored payload, as fetched. Addressed by the payload's own hash, which equals `content_hash` only when the source declares no `fields` (R2.17) |
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
      e. else store the payload itself as a snapshot, at a path
         derived from its own hash (R2.17), then update the ledger row
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

### Sources that declare no fields

A projection only means something for a structured payload. A markdown file or a
PDF from a folder has no fields to project onto, and the whole payload is the
content.

So the rule is general rather than per connector:

| The source declares | Hashed |
|---|---|
| `fields: [key, summary, …]` | the payload projected onto those fields, keys ordered canonically |
| no `fields` | the payload exactly as received |

Nothing is normalised away for a folder source — which is the correct behaviour
for it, because every byte of the file is meaningful. It also means a folder
source detects a change that alters only whitespace. That is deliberate: for a
structured source, whitespace in the rendered HTML is noise; for a file someone
dropped in a folder, an edit is an edit.

## Storage

Snapshots are content-addressed under the workspace's `.dossier/` directory
(R0.8), sharded two levels deep so that a source with tens of thousands of items
does not produce one enormous directory:

```
.dossier/snapshots/a3/f9/a3f9c1e2…      (64 hex characters, SHA-256, R0.7)
```

The shard is the first two pairs of characters of the hash itself, so the path is
a pure function of the content and needs nothing else to compute.

## Must hold

### R2.1 — an item whose remote version is unchanged is not fetched

Where the source offers a version marker, it is trusted and the payload is never
requested.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.needs_fetch`)
- **Proved by:** `tests/unit/test_R002_1__unchanged_remote_version_is_not_fetched.py`
- **Status:** MET

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
- **Status:** MET

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
- **Status:** MET

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
- **Status:** MET

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
- **Status:** SUPERSEDED by R2.14

> Superseded because it is two claims joined by an "and", and only one of them
> holds for every source. A source with no version marker -- a folder -- cannot
> know an item is unchanged without reading it, because R1.5 forbids fabricating
> a marker and its counter-example rules out mtime specifically. So "fetches zero
> payloads" is unreachable there, while "writes zero snapshots" holds everywhere.
> R2.14 and R2.15 are the two halves, each scoped to where it is true. Kept in
> place with its examples, because the reasoning above is the answer to "why is
> this split" and it belongs next to the thing that was split.

| # | Given | Then |
|---|-------|------|
| 1 | `dossier sync incident-audit` run twice, nothing changed between runs | the second run reports `0 fetched`, and the summary line reports `0 new snapshots · 0 tombstoned` |
| 2 | the snapshot store after the second run | byte-identical to its state after the first |
| 3 | the ledger after the second run | identical apart from `last_seen` and `last_sync_at` (R2.9) |
| 4 | *counter-example* — one fixture file edited between the two runs | that one item is fetched and snapshotted; the others still report no work |

### R2.14 — a second sync with nothing changed writes zero snapshots

Holds for every source, whatever it can or cannot tell us about its own
versions. Re-reading a payload is cheap and sometimes unavoidable; re-storing one
is neither, and a second snapshot of identical content would make the store lie
about what changed.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync`)
- **Proved by:** `tests/acceptance/test_R002_14__second_sync_writes_no_snapshot.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier sync incident-audit` run twice over a folder source, nothing changed | the summary reports `0 new snapshots · 0 tombstoned` |
| 2 | the snapshot store after the second run | byte-identical to its state after the first, including modification times |
| 3 | the ledger after the second run | identical apart from `last_seen` and `last_sync_at` (R2.9) |
| 4 | one fixture file edited between the two runs | `1 new snapshots`; the other two documents still write nothing |
| 5 | *counter-example* — the number of payloads read on the second run | not constrained here; a source with no version marker must read to know (R2.15) |

### R2.15 — a second sync fetches zero payloads from a source that exposes a version marker

Where the source can vouch that nothing moved, we take its word and never ask for
the payload. Where it cannot, we read and let the content hash decide (R2.2).

The split matters because the cost is different in kind. A Jira query returning
"nothing changed" is one request; a folder of 4,000 files is 4,000 reads however
the answer comes out.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync`)
- **Proved by:** `tests/acceptance/test_R002_15__version_marker_avoids_the_fetch.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a source whose items carry `remote_version`, synced twice with nothing changed | the second run reports `0 fetched` |
| 2 | the same source with `OPS-114` moving `v37` to `v38` | `1 fetched`; the rest are not read |
| 3 | a source whose items carry no `remote_version`, synced twice | every item is read on both runs, and the run says so rather than reporting `0 fetched` |
| 4 | *counter-example* — an item whose marker is unchanged but whose payload was edited behind the source's back | not fetched, and therefore not detected. That is the cost of trusting a marker, and it is why a source that cannot supply one must not pretend (R1.5) |

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
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` active in the ledger, absent from a full listing | `state=tombstoned`; the row and the snapshot at `a3f9c1e2` both remain |
| 2 | a run pinned to `a3f9c1e2`, replayed after that tombstoning | resolves and reproduces byte-for-byte (R4.7) |
| 3 | `INC-4821` returning to scope at a later sync | the same row goes back to `active`; `first_seen` is not rewritten |
| 4 | *counter-example* — an incremental listing with `since` set, which `INC-4821` is legitimately absent from | nothing is tombstoned; tombstoning is computed only against a full listing (R1.3) |

### R2.8 — an interrupted sync leaves a consistent ledger

Every row present refers, through its `snapshot_path`, to a snapshot that exists
and hashes to the address that path gives (R2.17). The failure mode this rules
out is a ledger claiming content the store does not hold, which turns into an
unresolvable run months later.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync`)
- **Proved by:** `tests/unit/test_R002_8__interrupted_sync_leaves_a_consistent_ledger.py`
- **Status:** MET

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
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | two syncs of `incidents-manual`, nothing changed | ledger rows identical apart from `last_seen` |
| 2 | the same, with the ledger serialised for comparison | identical bytes once the two time columns are excluded |
| 3 | the two syncs run under different locales and timezones | still identical; no locale-formatted value is stored (R0.4) |
| 4 | *counter-example* — `first_seen` on a row created by the first sync | set once and never rewritten, so it is identical by definition rather than by exclusion |

### R2.10 — a source that declares no `fields` hashes its payload as received

Normalisation projects a structured payload onto declared fields. A payload with
no declared fields has nothing to project onto, and every byte of it counts.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.normalise`)
- **Proved by:** `tests/unit/test_R002_10__a_source_without_fields_hashes_raw_bytes.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-manual`, a folder source with no `fields`, holding `audit-note.md` | the content hash is SHA-256 of the file's bytes, unchanged by any projection |
| 2 | the same file with one trailing space added | a different hash, so a new snapshot; for a dropped file, an edit is an edit |
| 3 | `incidents-jira`, which declares `fields`, whose rendered-HTML field changed | the same hash; the projection excluded that field (R2.2) |
| 4 | *counter-example* — a source declaring `fields: []` | a load-time error, not "hash everything". An empty list is a projection onto nothing, which no payload can satisfy (R3.9) |

### R2.11 — a snapshot's path is derived from its content hash alone

`.dossier/snapshots/<first two>/<next two>/<full hash>`. Nothing else enters the
path: not the source id, not the item key, not the fetch time.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.store.snapshot_path`)
- **Proved by:** `tests/unit/test_R002_11__snapshot_path_is_derived_from_the_hash.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | content hashing to `a3f9c1e2…` | `.dossier/snapshots/a3/f9/a3f9c1e2…`, the full 64 characters as the filename |
| 2 | the same bytes arriving from `incidents-jira` and from `incidents-manual` | one snapshot, referenced by two ledger rows; content addressing deduplicates (R1.6) |
| 3 | the same bytes fetched a year apart | the same path; time is not part of it |
| 4 | *counter-example* — two items with the same key in different sources | unrelated to the path; the ledger separates them by `source_id`, the store does not need to |

### R2.12 — `dossier sync <pipeline>` syncs the sources that pipeline declares

Sync takes a pipeline name, not a configuration path. A pipeline names both its
`sources` and its `reference` sources, and both must be held before it can run.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.sync`)
- **Proved by:** `tests/acceptance/test_R002_12__sync_takes_a_pipeline_name.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier sync incident-audit`, whose pipeline declares `sources: [incidents-manual]` | that source is synced |
| 2 | a pipeline declaring `reference: [procedures-confluence]` as well | both are synced; reference documents are inputs and must be held too |
| 3 | `dossier sync no-such-pipeline` | an error naming the pipeline and where it was looked for; nothing is fetched |
| 4 | *counter-example* — a source in `sources.yaml` that no pipeline names | not synced; the pipeline decides what is worth holding, not the source list |

### R2.13 — sync reports what it did, per source and in total

The counts are the interface. "Tomorrow's 420 issues cost 20 downloads" is only
credible if the command says so.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.sync`)
- **Proved by:** `tests/acceptance/test_R002_13__sync_reports_counts_per_source.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira` holding 420 items, 18 changed and 2 new | a line reading `incidents-jira  420 known · 18 changed · 2 new -> 20 fetched` |
| 2 | the end of the run | a summary line reading `ledger updated · 21 new snapshots · 0 tombstoned` |
| 3 | a source where nothing changed | still listed, reporting `-> 0 fetched`; a silent source is indistinguishable from a skipped one |
| 4 | *counter-example* — a source that failed mid-sync | reported as failed with its error, and excluded from the fetched counts; a failure is not zero work (R1.9) |

### R2.16 — the ledger records the media type its connector reported

A snapshot's media type is whatever its connector said it was, recorded when the
payload was fetched. Nothing downstream re-derives it: a name on disk is not
evidence about content (R8.3), and conversion may not re-fetch to ask (R0.1).

The connector may have had to guess — a folder source has only the filename to go
on — and that is fine. What matters is that the guess is made once, by the only
component that saw the source, and is then a recorded fact rather than something
each reader works out again and disagrees about.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.ledger`)
- **Proved by:** `tests/unit/test_R002_16__the_ledger_records_the_media_type.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` fetched from a folder source as `text/markdown` | the row records `text/markdown`, and conversion reads it from there (R8.5) |
| 2 | a second sync where `OPS-114` is unchanged and never fetched | the recorded media type is unchanged, not cleared; nothing re-derives it (R2.15) |
| 3 | `OPS-114` exported from Confluence as a PDF | `application/pdf`, whatever its key looks like |
| 4 | *counter-example* — a file named `notes.pdf` whose connector reported `text/markdown` | `text/markdown` is recorded and used; the connector's answer is the record, and the name is never consulted again (R8.3 example 4) |

### R2.17 — a held document is the raw payload its ledger row's `snapshot_path` addresses

Normalisation decides whether an item changed; it never decides which bytes are
held. A row keeps both answers: `content_hash`, the normalised hash that change
detection compares, and `snapshot_path`, the address of the payload exactly as
fetched. For a source that declares no `fields` the two coincide (R2.10), which is
why reading a document by its `content_hash` looked correct until a source
declared `fields` -- that hash addresses a projection nothing ever stored.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.ledger`)
- **Proved by:** `tests/unit/test_R002_17__a_held_document_is_its_raw_snapshot.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` synced from `incidents-jira`, which declares `fields` | its row's `snapshot_path` addresses the payload as fetched: the file exists there, and its SHA-256 is the path's last segment |
| 2 | `incident-audit` resolved after that sync | the manifest pins `INC-4821` by the address its row's `snapshot_path` gives, not by its `content_hash` (spec 004) |
| 3 | `INC-4821` converted | conversion reads the payload at that address, byte for byte |
| 4 | `INC-4821` synced again after only its rendered-HTML field changed | no new snapshot and the same `snapshot_path`; the projection cannot tell the two payloads apart, so the first stays the one held (R2.2) |
| 5 | *counter-example* — `audit-note.md` from `incidents-manual`, which declares no `fields` | `snapshot_path` and `content_hash` name the same file; nothing changes where the two hashes coincide (R2.10) |
