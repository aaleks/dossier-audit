# 000 — Overview, vocabulary and global invariants

**Status:** Partially implemented
**Rules:** R0.1 – R0.8

## Purpose

`dossier` collects documents from heterogeneous sources, runs a configurable
sequence of prompt stages over them, and produces a report whose every claim can
be traced to a source document — and whose accuracy is measured against
human-verified answers.

The first use case is auditing incident reports. The system is not specific to
it. A new use case is a folder of prompts plus a configuration block.

## Non-goals

- Not a general workflow orchestrator. Stages are a linear sequence over
  documents, not a branching agent graph.
- Not a search or retrieval-augmented chat system.
- Not a replacement for the source systems. `dossier` reads; it never writes back.

## Vocabulary

| Term | Meaning |
|---|---|
| **source** | A configured origin of documents: a folder, a Jira query, a Confluence space. |
| **connector** | The code implementing one source *type*. |
| **item** | One addressable thing in a source: an issue, a page, a file. |
| **snapshot** | An immutable, content-addressed copy of an item as fetched at a point in time. |
| **ledger** | The record of which items are held, at which remote version and content hash. |
| **document** | A converted snapshot — markdown text and/or page images — ready for a stage. |
| **stage** | One prompt applied over documents, producing structured output. |
| **pipeline** | An ordered list of stages plus the sources they read. |
| **run** | One execution of a pipeline, pinned to specific snapshots. |
| **manifest** | The frozen, fully-resolved description of a run. |
| **gold set** | Documents with human-verified expected answers. |
| **score** | The measured agreement between a run's output and the gold set. |

## The hash boundary

```
   sync  ──▶  store  ┃  convert  ──▶  stages  ──▶  score
                     ┃
  mutable, remote,   ┃   local, frozen, identical on every run
  not repeatable     ┃
```

Everything left of the boundary may touch the network and may return different
results on different days. Everything right of it is a pure function of content
hashes. This separation is the reason a run from six months ago can be
reproduced exactly.

In the code the boundary is a package boundary:
`dossier.infrastructure.connectors` is the only place a network client may be
imported. Everything else is right of the line. See `docs/architecture.md`.

## Hashing

One algorithm, everywhere: **SHA-256 over bytes, rendered as 64 lowercase hex
characters**. It covers snapshot content hashes (spec 002), prompt, schema and
config file hashes, and every cache key (spec 005).

The choice is deliberately boring. `hashlib` ships with Python, so there is no
dependency to pin and no build to reproduce; the digest is stable across
versions, platforms and locales, which is what R0.4 and R5.6 require; and a
stored snapshot can be verified with a standard `sha256sum` by someone who does
not have `dossier` installed.

Examples throughout these specs write hashes as **8-character prefixes** —
`a3f9c1e2`, `77c1b40a`. That is a display convention for readability. The stored
value, the ledger column and every cache key hold the full 64 characters.

## Workspace layout

A workspace is a directory holding `sources.yaml`. Commands operate on the
current working directory as the workspace root.

```
sources.yaml                     configuration, committed
pipelines/<name>/pipeline.yaml   configuration, committed
gold/<name>/                     verified answers, committed
runs/<run_id>/                   run outputs and manifest, reviewable
.dossier/                        machine-local state, never committed
  snapshots/ab/cd/<hash>         the immutable store
  ledger.db                      what is held, at which version and hash
  cache/                         stage and convert artifacts
```

The split is between what a human reads or reviews and what the machine
regenerates. `runs/` holds the report and the manifest someone will open, so it
sits in the open; `.dossier/` holds state that is derived, large, and meaningless
without the tool.

## Must hold

These six are global: every other spec assumes them, and a violation anywhere
breaks reproducibility everywhere. They were numbered `G1`–`G6` in the first
draft of this spec and are now `R0.1`–`R0.6`, so that one identifier scheme
covers every rule in the repository.

### R0.1 — nothing right of the hash boundary performs network I/O

Only `dossier.infrastructure.connectors` may import a network client. Convert,
run and eval never reach the network on any code path, including error paths and
imports made lazily inside a function body.

- **Kind:** deterministic
- **Layer:** architecture
- **Proved by:** `tests/architecture/test_R000_9__only_two_packages_reach_the_network.py`
- **Status:** SUPERSEDED by R0.9

| # | Given | Then |
|---|-------|------|
| 1 | `dossier/application/convert.py` imports `httpx` | violation, naming the file, the line and the import |
| 2 | `dossier/domain/keys.py` imports `urllib.request` inside a function body | violation; a lazy import is still an import |
| 3 | *counter-example* — `dossier/infrastructure/connectors/jira.py` imports `httpx` | allowed; this package is left of the boundary and is the only one that is |
| 4 | *counter-example* — `dossier/infrastructure/store.py` opens a file on local disk | allowed; local file IO is not network IO |

### R0.2 — a stored snapshot is never modified or deleted in place

Once written, the bytes at a snapshot path never change and the path is never
removed. New content means a new content-addressed path. Tombstoning marks the
ledger, never the store.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.store`)
- **Proved by:** `tests/unit/test_R000_2__snapshot_store_never_overwrites.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` stored at `a3f9c1e2`, then stored again with identical bytes | the existing file is left untouched and no write occurs |
| 2 | `INC-4821` stored at `a3f9c1e2`, then its payload changes | a second snapshot appears; `a3f9c1e2` still reads back byte-for-byte |
| 3 | `INC-4821` leaves the Jira query scope | ledger row becomes `state=tombstoned`; the snapshot at `a3f9c1e2` remains readable |
| 4 | *counter-example* — a partially written snapshot from an interrupted sync | may be discarded; it was never a complete snapshot and no ledger row refers to it (R2.8) |

### R0.3 — every stage artifact has a sibling provenance record

Each artifact is written with a `<name>.meta.json` naming its inputs by hash,
the prompt version, the schema version, the model identifier and the timestamp.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R000_3__every_artifact_has_a_provenance_record.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `verify` produces `verify/INC-4821.json` | `verify/INC-4821.meta.json` sits beside it, listing inputs `a3f9c1e2` and `77c1b40a` |
| 2 | the same artifact is served from cache rather than recomputed | the provenance record is present and identical (R5.5) |
| 3 | *counter-example* — `INC-4821` fails validation twice and produces no artifact | no artifact and no provenance record; the failure is reported, not recorded as an output (R6.9) |

### R0.4 — the resolved manifest and every cache key are byte-identical across runs and machines

Given the same snapshots, prompts, schemas and model identifier, resolution and
key computation produce identical bytes in any process, on any machine, under
any locale or timezone.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`, `dossier.domain.resolution`)
- **Proved by:** `tests/unit/test_R000_4__manifest_and_keys_are_byte_identical.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `incident-audit` resolved twice in one process | identical manifest bytes apart from run id and start time (R4.8) |
| 2 | the same inputs under `TZ=UTC` and under `TZ=Asia/Tokyo` | identical cache keys |
| 3 | the same inputs in two processes with different `PYTHONHASHSEED` | identical cache keys; no reliance on `hash()` or set iteration order |
| 4 | *counter-example* — the run id `20260806T142203Z-4f1a` | differs between runs by design, and is excluded from every key |

### R0.5 — anything that can change an output is part of that output's cache key

If changing something changes the result, changing it invalidates the cache. The
contrapositive is the useful half: a cache hit is a promise that nothing relevant
changed.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R000_5__key_covers_every_output_determining_input.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `prompts/02_verify.md` is edited | the `verify` key changes |
| 2 | `schemas/incident.json` is edited | the `verify` key changes |
| 3 | the pinned model changes to `anthropic:claude-sonnet-4-5-20250929` from another pin | every stage key changes (R5.3) |
| 4 | *counter-example* — the cache directory is deleted | no key changes; only the time taken (R5.9) |

### R0.6 — model identifiers are pinned exactly, and floating aliases are rejected at load time

A `model` value must name an exact, immutable version. An alias a provider may
re-point is rejected before any work begins.

An id is pinned when it is in its provider's immutable form -- for `anthropic`,
a dated snapshot ending `-YYYYMMDD`; each other provider's form is its own and is
stated when that provider is added -- or when `dossier.domain.model_id` names it
as an id the provider documents as fixed. That list is short and reviewed: each
entry is a claim about a provider, and a wrong one is a floating alias let
through.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.model_id`)
- **Proved by:** `tests/unit/test_R000_6__floating_model_aliases_are_rejected.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `model: anthropic:claude-sonnet-4-5-20250929` | accepted |
| 2 | `model: anthropic:claude-sonnet-4-5` | load-time error naming the file, the line and the alias |
| 3 | `model: anthropic:claude-sonnet-latest` | load-time error |
| 4 | *counter-example* — a run replayed from `runs/20260806T142203Z-4f1a/manifest.json` | the manifest's recorded identifier is used as-is; the check already happened when that run was resolved (R4.7) |
| 5 | `model: anthropic:claude-opus-5`, undated and listed in `dossier.domain.model_id` | accepted; a date suffix is how most ids are pinned, not what pinned means |

### R0.7 — every hash is SHA-256 over bytes, rendered as 64 lowercase hex characters

One algorithm for snapshot content hashes, file hashes and cache keys. No
truncation is stored, and no other digest appears anywhere in the system.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.hashing`)
- **Proved by:** `tests/unit/test_R000_7__hashes_are_sha256_lowercase_hex.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the bytes of `INC-4821.md` | the ledger `content_hash` equals `sha256sum` of that file, all 64 characters |
| 2 | the same bytes hashed on Windows and on Linux | identical; the digest is over bytes, and `.gitattributes` keeps the bytes identical |
| 3 | a hash rendered for a log line or a spec example | may be shortened to 8 characters for display; the stored value is never truncated |
| 4 | *counter-example* — a run id such as `20260806T142203Z-4f1a` | not a hash; it is a timestamp and a suffix, and it is excluded from every key (R0.4) |

### R0.8 — generated state lives under `.dossier/`, and run outputs under `runs/`

Machine-local state is derived, large and regenerable; run outputs are read by
people. The two are kept apart so that deleting the first is always safe.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.workspace`)
- **Proved by:** `tests/unit/test_R000_8__workspace_layout_separates_state_from_output.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | a completed `dossier sync` in a workspace | snapshots under `.dossier/snapshots/`, the ledger at `.dossier/ledger.db`, and nothing written outside `.dossier/` |
| 2 | a completed `dossier run` | the manifest and artifacts under `runs/<run_id>/`, which is not hidden and not gitignored |
| 3 | `.dossier/` deleted, then the same pipeline re-run after a re-sync | byte-identical outputs; only the time taken differs (R5.9) |
| 4 | *counter-example* — `sources.yaml`, `pipelines/`, `gold/` | configuration and verified answers, committed to git; they are inputs, and deleting them is not recoverable |

## Spec index

`specs/README.md` holds the index and the status of each spec.

### R0.9 — exactly two packages may reach the network, and a model is asked only on a cache miss

`dossier.infrastructure.connectors` fetches source payloads.
`dossier.infrastructure.models` asks a model. Nothing else imports a network
client, on any code path, including error paths and imports made lazily inside a
function body.

Supersedes R0.1, which said only connectors may reach the network and that `run`
never does. That was already untrue of the system this project is building: a
stage asks a model, and asking is the point. R0.1 was observably true only
because no model client existed yet, and a rule that becomes false the moment the
product works is a rule that would have been quietly deleted rather than
reviewed.

What the hash boundary actually promises is not "no network right of it". It is
that **everything right of it is reproducible**: a stage's answer is pinned by a
key over its prompt, schema, model identifier and input hashes (spec 005), stored
with a provenance record (R0.3), and never asked again. So the boundary holds
even though a model is on the far side of it, and the invariant that keeps it
holding is the second half of this rule: a model is reached on a cache miss
during execution and at no other time.

- **Kind:** deterministic
- **Layer:** architecture
- **Proved by:** `tests/architecture/test_R000_9__only_two_packages_reach_the_network.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier/application/convert.py` imports `httpx` | violation, naming the file, the line and the import |
| 2 | `dossier/domain/keys.py` imports `urllib.request` inside a function body | violation; a lazy import is still an import, and deferring one defers when the network becomes reachable, not whether |
| 3 | `dossier/infrastructure/models/anthropic.py` imports `anthropic` | allowed; this package and `connectors` are the only two, and the SDK is a network client whatever it is named |
| 4 | `dossier.application.replay` and `dossier.domain.scoring` given a model client | they take no such parameter; a replay reproduces what was cached and a non-judge scorer compares values (R4.7, R7.10) |
| 5 | `dossier run --plan` over a pipeline where every step would re-run | zero model calls; planning reports work rather than doing it (R4.6) |
| 6 | *counter-example* — `dossier/infrastructure/store.py` opens a file on local disk | allowed; local file IO is not network IO |
| 7 | *counter-example* — a stage with no cache entry, during `dossier run` | reaches the model, once, and the answer is cached with its provenance record. That is the one permitted crossing, and R5.5 is the claim that it never happens twice for the same inputs |
