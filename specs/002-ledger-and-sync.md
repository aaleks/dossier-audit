# 002 — Ledger and incremental sync

**Status:** Implemented
**Rules:** R2.1 – R2.27

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

A `revisions` table keeps every address a row has ever held. One row is appended
when an item is first seen and one each time its row is repointed; nothing in it
is ever updated or deleted (R2.19). The `items` table answers "what is held
now"; `revisions` answers "what was held before, and since when".

| Column | Meaning |
|---|---|
| `source_id` / `key` | The row this revision belongs to |
| `content_hash` | The normalised hash the row held |
| `snapshot_path` | The address the row pointed at |
| `recorded_at` | The start time of the sync that wrote it |

## Sync algorithm

```
1.  since := last_sync_at - overlap        (overlap default 24h)
              or None: never synced, `fields` changed (R2.3), or `--full` (R2.22)
2.  refs  := connector.list(since)
    complete := since is None or connector.lists_everything   (R1.11, R2.21)
3.  for each ref:
      a. if remote_version is present and equals the ledger row  -> skip
      b. payload := connector.fetch(ref.key)
      c. h := hash(normalise(payload))
      d. if h equals the ledger row's content_hash               -> touch only
      e. else store the payload itself as a snapshot, at a path
         derived from its own hash (R2.17), then update the ledger row
      f. repeat (b)-(e) independently for each attachment
4.  if complete: items in the ledger that were active but absent from
    the listing are marked tombstoned; they are never deleted
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
- **Status:** MET

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
evidence about content (R8.3), and conversion may not re-fetch to ask (R0.10).

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

### R2.18 — `dossier sync` names each changed item under its source line, with the address it held and the one it holds now

`1 changed` over a corpus of four thousand is not something a person can check,
which is the argument R4.12 already makes for `plan`. The two addresses are the
row's old and new `snapshot_path`, as full 64-character hashes: the things a
person can open and diff. A `content_hash` is not printed, because for a source
declaring `fields` it addresses a projection nothing stored (R2.17). Named lines
are in key order.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.sync`)
- **Proved by:** `tests/unit/test_R002_18__a_changed_outcome_names_both_addresses.py`, `tests/unit/test_R002_18__the_source_report_carries_each_repointed_item.py`, `tests/acceptance/test_R002_18__sync_names_each_changed_item_with_both_addresses.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4822` re-fetched, ledger at `0e52dd18`, payload hashing to `77c1b40a` | under the `incidents-jira` line: `      INC-4822  0e52dd18… -> 77c1b40a…`, each the full 64 characters |
| 2 | the same, from `incidents-jira`, which declares `fields` | the two addresses are its old and new `snapshot_path`, not its content hashes; for `incidents-manual`, which declares none, the two coincide (R2.10) |
| 3 | `INC-4821` at `v37` unchanged, its attachment `report.pdf` replaced (R2.6) | `report.pdf` is named on its own line; `INC-4821` is not |
| 4 | *counter-example* — `audit-note.pdf` re-read, same hash | not named; `0 changed`, and only `last_seen` moved (R2.2) |
| 5 | *counter-example* — a first sync, `4 new` | nothing named; a first sync of 4,000 items would print 4,000 lines that say nothing the count does not |

### R2.19 — every address a ledger row has ever held is retained in an append-only `revisions` table

The store keeps every snapshot (R0.2) and the ledger forgot which item each one
belonged to: after a repoint the previous address was recoverable only by
elimination. A revision row is written in the same transaction as the `items`
row it describes, so the two cannot disagree (R2.8).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.ledger`)
- **Proved by:** `tests/unit/test_R002_19__the_ledger_keeps_every_address_a_row_has_held.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4822` repointed from `0e52dd18` to `77c1b40a` | two revision rows for `INC-4822`, in that order, after the `items` row holds only `77c1b40a` |
| 2 | `INC-4901` seen for the first time | one revision row, written with the `items` row; the first version is otherwise exactly the one nobody can recover |
| 3 | `INC-4822` at `0e52dd18`, then `77c1b40a`, then `0e52dd18` again | three rows; the sequence is the record, not the set of hashes |
| 4 | a ledger created before this table existed, opened | `revisions` is created and seeded with one row per `items` row, `recorded_at` set to that row's `last_seen`: the last sync that confirmed those bytes |
| 5 | *counter-example* — `audit-note.pdf` re-read, same hash | no revision row; an unchanged source still produces identical ledger content (R2.9) |
| 6 | *counter-example* — `INC-4821` tombstoned (R2.7) | no revision row; state is not content |
| 7 | *counter-example* — the process killed between writing the snapshot and repointing the row (R2.8) | no revision row; the history never claims a repoint the `items` table does not show |

### R2.20 — `dossier sync` names each item it tombstones under its source line

`1 tombstoned` has the same problem as `1 changed`: it says something left and
not what.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.sync`)
- **Proved by:** `tests/unit/test_R002_20__the_source_report_carries_each_departed_key.py`, `tests/acceptance/test_R002_20__sync_names_each_tombstoned_item.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` active in the ledger, absent from a full listing | under the `incidents-jira` line: `      INC-4821  tombstoned` |
| 2 | `INC-4821` and `INC-4822` both absent | two lines, in key order, and the summary still reads `2 tombstoned` (R2.13) |
| 3 | *counter-example* — an incremental listing with `since` set, `INC-4821` legitimately absent | nothing tombstoned, nothing named (R2.7 row 4) |
| 4 | *counter-example* — `INC-4821` returning to scope with the same bytes (R2.7 row 3) | not named as tombstoned: it is not tombstoned. It is named as returned (R2.25), and R2.18 does not name an unchanged hash |

### R2.21 — tombstones are computed against any listing that is complete, whether nothing was subtracted or the connector never subtracts

A listing is complete for one of two reasons: sync asked for everything
(`since=None`), or the connector declares that it returns everything whatever
it is asked (`lists_everything`, R1.11). Before this rule only the first
counted, and a folder -- which returns everything on every sync -- was believed
only on its first one. The safety rule does not move: an incremental listing
from a connector that narrows is still never subtracted from (R2.7 row 4).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.listing_is_complete`)
- **Proved by:** `tests/unit/test_R002_21__a_listing_the_connector_declares_complete_is_subtracted_from.py`, `tests/acceptance/test_R002_21__a_file_deleted_from_a_folder_is_tombstoned_on_the_next_sync.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-manual` watermarked `2026-08-06T09:00:00Z`, so `since = 2026-08-05T09:00:00Z`; the connector declares `lists_everything`; `audit-note.pdf` deleted from the folder | the listing is complete; `audit-note.pdf` goes `tombstoned` on this sync and is named under the source line (R2.20); the summary reads `1 tombstoned` |
| 2 | any connector asked with `since=None` | complete; the path every sync took before this rule, unchanged |
| 3 | `audit-note.pdf` restored to the folder before the following sync | the same row goes back to `active`; `first_seen` is not rewritten (R2.7 row 3, reachable for a folder for the first time) |
| 4 | *counter-example* — `incidents-jira` with `since = 2026-08-05T09:00:00Z`, `lists_everything` `False`, `INC-4821` legitimately absent | not complete; `0 tombstoned` (R2.7 row 4) |

### R2.22 — `dossier sync --full <pipeline>` lists every source the pipeline declares without a window

A source that narrows its listings (R1.11) is subtracted from only when sync
asked it for everything, and until now that happened once: the first sync, or a
change to `fields` (R2.3). `--full` is the same question asked on demand, so an
issue deleted from Jira can be tombstoned without editing the source's
projection to force it. It is a full *listing*, not a re-evaluation: an item
whose version marker is unchanged is still not fetched (R2.1), so on a quiet
source the flag costs one listing and nothing else.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.sync`)
- **Proved by:** `tests/unit/test_R002_22__a_full_sync_starts_from_nothing.py`, `tests/acceptance/test_R002_22__sync_full_tombstones_what_a_windowed_source_dropped.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira` watermarked `2026-08-06T09:00:00Z`, `INC-4821` deleted at the source, `dossier sync --full incident-audit` | the connector is asked `list(since=None)`; `INC-4821` goes `tombstoned` and is named under the source line (R2.20) |
| 2 | the same, with every remaining issue's `remote_version` unchanged | `0 fetched`, `0 new snapshots`; a full listing is not a re-fetch (R2.1) |
| 3 | the same, no item failing | `last_sync_at` advances to the sync's start time as on any sync (R2.8 row 4); `--full` asks one question, it does not reset the watermark |
| 4 | *counter-example* — `dossier sync incident-audit` without the flag | the connector is asked `list(since=2026-08-05T09:00:00Z)`; `INC-4821`, absent from that listing, stays `active` (R2.7 row 4) |

### R2.23 — a key whose fetch failed is asked again at the next sync, whether or not the listing returns its item

R2.8 holds the watermark back when an item fails, so the next sync's window
starts where the failed one did. That returns the item again only if it changed
inside the window. A file that failed while its item stood still -- a Confluence
export refused under `--full`, a Jira attachment that timed out -- was not asked
about again. The next sync then had nothing to fail on, moved the watermark
past the failure, and never reported it again. Playground exercise 15 found this
against `cwiki.apache.org`.

So the ledger remembers what it is owed. A key whose fetch failed is recorded
with the item carrying it. At the next sync, an owed key's item is visited
whether or not the listing returned it. An owed item is fetched. For an owed
file, its item's files are listed again, and the item is not fetched again
unless its own marker moved. Whether an item is visited is a decision over the
owed keys and the listing, and it is made in `domain`.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.owed_items`), applied by application (`dossier.application.sync`), recorded by infrastructure (`dossier.infrastructure.ledger`)
- **Proved by:** `tests/unit/test_R002_23__a_failed_key_is_asked_again.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `81920114.pdf` refused `403` by `dossier sync --full`, then a plain sync whose window returns no page | the export is asked again, once; still refused, it is reported again and the watermark stays where it was (R2.8) |
| 2 | the same, and the export succeeds on the retry | stored and recorded; the sync after that does not ask for it |
| 3 | `INC-4821/report.pdf` timed out, and `INC-4821` unchanged since | the file is asked again; the issue is not fetched, its marker being unchanged (R2.1) |
| 4 | *counter-example* — the file, owed, and its item no longer carrying it | not asked; it is owed nothing, and is not tombstoned either, since it was never held |
| 5 | *counter-example* — an owed item that a complete listing no longer returns | tombstoned (R2.7), and neither it nor its files are asked |

### R2.24 — a change to a source's own keys makes its next listing complete, and fetches nothing that did not change

The keys a connector declares (R1.10) -- `url` and `query`, a folder's `path`,
Confluence's `export` -- decide what a listing answers. When one of them
changes, an incremental listing answers a question about the source as it was.
A Jira query narrowed to `labels = sev1` leaves every issue it no longer matches
`active` until `--full`. `export: pdf` added to a source already synced asks for
no export until a page changes, and taken away it tombstones nothing. So the
hash of those keys is recorded, and a sync that finds it changed lists without a
window, as `--full` does (R2.22). It is a complete listing, not a re-evaluation:
an item whose marker has not moved is not fetched (R2.1). A key that only names
a credential or a route costs one complete listing when it changes, and
separating them would be a second list to keep right for no saving that
matters.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.sync_window`, `dossier.domain.sync.listing_hash`)
- **Proved by:** `tests/unit/test_R002_24__a_changed_source_is_listed_whole.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `procedures-confluence` synced, then `export: pdf` added | the next sync lists every page without a window; each `<page id>.pdf` is fetched, and no page is (R2.1) |
| 2 | `export: pdf` taken away | the next sync lists without a window, and every `<page id>.pdf` is tombstoned (R2.6 row 3) |
| 3 | `incidents-jira`'s `query` narrowed to `project = INC AND labels = sev1` | the next sync lists without a window; `INC-4822`, no longer matched, is tombstoned now rather than at the next `--full` (R2.7) |
| 4 | the sync after that, nothing changed | lists from the window again (R2.4) |
| 5 | *counter-example* — `watermark_overlap: 48h` | not a key of the source's own. It moves the window (R2.4), and the listing stays windowed |
| 6 | *counter-example* — `fields:` changed | R2.3's re-evaluation, which fetches every item. This rule fetches none that did not change |
| 7 | a ledger written before this rule, holding no hash of the source's keys | the next sync lists without a window, once. An unknown hash cannot vouch that the last listing answered today's keys |

### R2.25 — `dossier sync` counts and names each item that returns after it was tombstoned, apart from known, changed and new

`known` counts the rows active before the sync, and `new` the keys the ledger has
never held. A tombstoned item a listing offers again is neither, so it was fetched
and counted nowhere. Restoring `audit-note.pdf` to its folder printed
`2 known · 0 changed · 0 new -> 3 fetched`: three fetched, and two accounted for.
Playground exercise 04 found it.

`returned` sits beside the other three, and is printed only when there is one,
so a sync where nothing came back reads as it always did (R2.13). Each returned
item is named under its source line (R2.20's reason). An item that comes back
with different bytes is counted as returned, not changed: `changed` counts items
that were known, and the returned line carries both addresses instead (R2.18's
reason).

An item a listing offers again goes back to `active` in any sync, windowed or
complete, as R2.7 row 3 says. Only a complete listing did this before, so an
item that came back unchanged in a windowed listing stayed tombstoned.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync`)
- **Proved by:** `tests/unit/test_R002_25__a_returning_item_is_counted_as_returned.py`, `tests/acceptance/test_R002_25__sync_names_what_came_back.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `audit-note.pdf` restored to `incidents-manual`'s folder with the bytes it had (R2.21 row 3) | `incidents-manual  2 known · 0 changed · 0 new · 1 returned -> 3 fetched`, and under it `      audit-note.pdf  returned` |
| 2 | `audit-note.pdf` restored with different bytes | `2 known · 0 changed · 0 new · 1 returned`, and `      audit-note.pdf  returned  c4a70b93… -> …`, both addresses in full as R2.18 prints them |
| 3 | `INC-4821` tombstoned by a `--full` sync, then offered again by a windowed listing with the bytes it had | counted and named as returned, and its row is `active` again (R2.7 row 3). Before this rule it stayed tombstoned |
| 4 | *counter-example* — a sync where nothing came back | the line R2.13 prints, with no `returned` term |
| 5 | *counter-example* — `INC-4822`, a key the ledger has never held | counted as new, not returned |

### R2.26 — what a connector's fetch asks for is part of the source configuration hash

A connector may declare what its fetch asks for beyond an item's address:
`fetch_asks`. It joins R2.3's projection in the source configuration hash. So a
connector that starts asking for more fetches every item it holds again, once,
and the next sync fetches only what changed. A connector that declares nothing
hashes as it did before this rule, so a source whose connector did not change is
not fetched again.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.source_config_hash`)
- **Proved by:** `tests/unit/test_R002_26__a_change_to_what_a_fetch_asks_fetches_everything_once.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira`, synced before its connector asked for `expand=names,schema` (R1.28) | the next sync fetches every issue again, and `INC-4821`'s new snapshot has `names` in it |
| 2 | the sync after that | `0 fetched`: the hash is recorded, and nothing changed |
| 3 | *counter-example* — `incidents-manual`, a folder source, whose connector declares nothing | the hash is the one it had before this rule, and nothing is fetched again |
| 4 | *counter-example* — `fields` reordered on `incidents-jira` | the hash does not change, as R2.3 row 2 says |

### R2.27 — a source whose listing fails is reported with the reason, is left as it was, and does not stop the sources after it

A listing can fail. A sitemap cannot be read (R1.29), a crawl cannot finish
(R1.38), a site answers `429` (R1.35), a server rejects a query. The sync of
that source stops there, and the source is left as a listing that never finished
leaves it:

- nothing it held is tombstoned, because the listing was not complete (R2.7);
- its watermark, configuration hash and listing hash stay where they were
  (R2.8, R2.3, R2.24);
- what it is owed stays owed (R2.23);
- an item stored before the listing failed stays stored.

The sources after it sync as they would have. `dossier sync` names the source
and the reason, ends a tracked run `FAILED`, and exits `1`. Before this rule the
failure left the command as a traceback, and the sources after it were not
synced at all. `www.python.org/about/` with `crawl: 5` did that on 2026-09-28.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync.sync_source`), reported in `dossier.cli.sync`
- **Proved by:** `tests/unit/test_R002_27__a_failed_listing_leaves_its_source_as_it_was.py`, `tests/acceptance/test_R002_27__a_source_that_cannot_be_listed_does_not_stop_the_others.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `vendor-docs`, whose sitemap answers `503`, synced before `incidents-manual` | `vendor-docs: listing failed:` and the reason, naming the sitemap and `503`. `incidents-manual` syncs, and the command exits `1` |
| 2 | `vendor-docs` holding its four pages, then its sitemap answering `503` | the four stay active, and its watermark and listing hash are the ones the last sync recorded |
| 3 | `escalation` owed from a fetch that failed (R2.23), and then the listing fails | `escalation` is still owed |
| 4 | a listing that returns two items and then fails | both are stored, and nothing held is tombstoned |
| 5 | a tracked sync of row 1 | the run ends `FAILED` |
| 6 | *counter-example* — a fetch that fails (R1.9) | not this rule: the listing goes on, and the item is owed (R2.23) |
