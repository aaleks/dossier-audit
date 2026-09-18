# 000 — Overview, vocabulary and global invariants

**Status:** Implemented
**Rules:** R0.1 – R0.13

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
- **Status:** SUPERSEDED by R0.10

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
- **Status:** MET

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
- **Status:** MET

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

"Anything" is anything a pipeline author or a run can change: prompts, schemas,
the pinned model, the inputs. What dossier itself says to a model -- the wrapper
a retry carries its error in, a client's request ceiling -- moves only when
dossier is released, and `dossier_version` in every provenance record is where
that is written down (R0.3). Keying it would turn every release into a full
re-run of every cache, to re-derive artifacts that had already validated.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R000_5__key_covers_every_output_determining_input.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `prompts/02_verify.md` is edited | the `verify` key changes |
| 2 | `schemas/incident.json` is edited | the `verify` key changes |
| 3 | the pinned model changes to `anthropic:claude-sonnet-4-5-20250929` from another pin | every stage key changes (R5.3) |
| 4 | *counter-example* — the cache directory is deleted | no key changes; only the time taken (R5.9) |
| 5 | *counter-example* — text dossier itself authors: the retry wrapper a validation error is sent back in (R6.2 row 3), a model client's `max_tokens`, its sampling settings | in no key; recorded by `dossier_version` (R0.3, R5.1 row 4). A change to what dossier says is a release, not a pipeline change: keying it would re-run every cache on every release, for artifacts that already validated |

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
- **Status:** MET

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
- **Layer:** domain (`dossier.domain.store`), application (`dossier.application.manifest`)
- **Proved by:** `tests/unit/test_R000_8__workspace_layout_separates_state_from_output.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a completed `dossier sync` in a workspace | snapshots under `.dossier/snapshots/`, the ledger at `.dossier/ledger.db`, and nothing written outside `.dossier/` |
| 2 | a completed `dossier run` | the manifest and artifacts under `runs/<run_id>/` (R0.11), which is not hidden and sits outside `.dossier/`; whether a workspace commits its runs is that workspace's own choice |
| 3 | `.dossier/` deleted, then the same pipeline re-run after a re-sync | byte-identical outputs; only the time taken differs (R5.9) |
| 4 | *counter-example* — `sources.yaml`, `pipelines/`, `gold/` | configuration and verified answers, committed to git; they are inputs, and deleting them is not recoverable |

### R0.13 — a `per_part` step writes each part under its document, as `runs/<run_id>/<step>/<document>/<part>.md`

R0.11 gives every artifact a path of `runs/<run_id>/<step>/<document>.json`. A
`per_part` step produces several artifacts for one document (R3.12), so one more
level exists: the document becomes a directory and each part is a file in it,
named as the container names it.

R0.11 is not superseded. It still describes every `per_file` and `aggregate`
step, which is every step that existed when it was written; this says what the
third mode does, and the two together cover all of them.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.store.output_path`)
- **Proved by:** `tests/unit/test_R000_13__a_per_part_artifact_is_filed_under_its_document.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `describe` over `INC-4830`, three pages, run `20260806T142203Z-4f1a` | `runs/20260806T142203Z-4f1a/describe/INC-4830/page-001.md` and two more beside it, with a provenance record each (R0.3) |
| 2 | the same, for a document whose key is `audit-note.pdf` | `describe/audit-note.pdf/page-001.md`; the key is a directory name exactly as it is a file name in R0.11, extension included |
| 3 | the second page of that document failing | `page-001.md` and `page-003.md` are written and `page-002.md` is not; a failed part leaves nothing, as a failed document does (R0.11) |
| 4 | *counter-example* — the `extract` step in the same run | `runs/<run_id>/extract/INC-4830.json`, unchanged; R0.11 still describes every step that is not `per_part` |

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
- **Status:** SUPERSEDED by R0.10

| # | Given | Then |
|---|-------|------|
| 1 | `dossier/application/convert.py` imports `httpx` | violation, naming the file, the line and the import |
| 2 | `dossier/domain/keys.py` imports `urllib.request` inside a function body | violation; a lazy import is still an import, and deferring one defers when the network becomes reachable, not whether |
| 3 | `dossier/infrastructure/models/anthropic.py` imports `anthropic` | allowed; this package and `connectors` are the only two, and the SDK is a network client whatever it is named |
| 4 | `dossier.application.replay` and `dossier.domain.scoring` given a model client | they take no such parameter; a replay reproduces what was cached and a non-judge scorer compares values (R4.7, R7.10) |
| 5 | `dossier run --plan` over a pipeline where every step would re-run | zero model calls; planning reports work rather than doing it (R4.6) |
| 6 | *counter-example* — `dossier/infrastructure/store.py` opens a file on local disk | allowed; local file IO is not network IO |
| 7 | *counter-example* — a stage with no cache entry, during `dossier run` | reaches the model, once, and the answer is cached with its provenance record. That is the one permitted crossing, and R5.5 is the claim that it never happens twice for the same inputs |

### R0.10 — exactly three packages may reach the network, and a model is asked only on a cache miss

`dossier.infrastructure.connectors` fetches source payloads.
`dossier.infrastructure.models` asks a model. `dossier.infrastructure.tracking`
sends records to MLflow (spec 010). Nothing else imports a network client, on
any code path, including error paths and imports made lazily inside a function
body.

Supersedes R0.9, which admitted two. An MLflow tracking server is reached over
HTTP, so the package that records to it is left of the line whether or not the
rule says so -- and `mlflow` was not counted as a network client, so R0.9's
check would have passed green while it was imported anywhere. Widening the
exemption is the decision; counting `mlflow` is what gives it teeth.

The third package changes nothing about what the boundary promises. Tracking
only *sends*: the port it is reached through has no method that returns anything
read from the server, so nothing MLflow holds can enter a key, a manifest or a
score, and everything right of the boundary stays reproducible whether tracking
is on or off (R10.4).

- **Kind:** deterministic
- **Layer:** architecture
- **Proved by:** `tests/architecture/test_R000_10__three_packages_reach_the_network.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier/application/convert.py` imports `httpx` | violation, naming the file, the line and the import |
| 2 | `dossier/domain/keys.py` imports `urllib.request` inside a function body | violation; a lazy import is still an import |
| 3 | `dossier/infrastructure/tracking/mlflow.py` imports `mlflow` | allowed; the third package, and the SDK is a network client whatever it is named |
| 4 | `dossier/application/run.py` imports `mlflow` | violation; `mlflow` counts as a network client, which it did not under R0.9 |
| 5 | the `Tracker` port in `dossier.domain.ports` | declares no method that returns anything read from the server |
| 6 | `dossier run --plan` over a pipeline where every step would re-run | zero model calls and zero tracking calls (R4.6, R11.1) |
| 7 | *counter-example* — `dossier/infrastructure/store.py` opens a file on local disk | allowed; local file IO is not network IO |
| 8 | *counter-example* — a stage with no cache entry, during `dossier run` | reaches the model, once, and the answer is cached with its provenance record; R5.5 is the claim that it never happens twice for the same inputs |

### R0.11 — a completed `dossier run` writes each artifact a step produced or served to `runs/<run_id>/<step>/<document>.json`, the same bytes the cache holds

The cache under `.dossier/` is where an artifact is *kept*; the run directory
is where a person *reads* it. Every other spec already names the second path --
R0.3's `verify/INC-4821.json`, R5.5, R5.8, and spec 005's provenance table,
where a path under a step id is "relative to that run's outputs" -- and this
rule is the one that makes it exist. R0.8 says which side of the line each
lives on; this rule says what the run side holds.

The name is the document key with `.json` appended, so the folder key
`PLAY-1001.md` becomes `extract/PLAY-1001.md.json` and `INC-4821` becomes
`extract/INC-4821.json`. Replacing the suffix would collide `PLAY-1001.md` with
`PLAY-1001.pdf`, which R4.10 says are two documents. A step with no `output`
declaration returns text rather than a field record, and its file carries `.md`.
An `aggregate` step's one artifact is filed under the reserved key `*` (spec
003), which is not a file name on every platform, and the step read every
document, so its file is `aggregate.json` or `aggregate.md`: named for what it
is rather than after any one document.

The copy is written as each document completes, never read back, and never
authority: `dossier` resolves every artifact from the cache by key, so a run
directory can be deleted, committed, or edited by a reviewer without any later
run noticing. Conversions are not copied; spec 008 leaves
`runs/<run_id>/converted/` undecided, and nothing here decides it.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.store.output_path`), application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R000_11__a_run_writes_its_artifacts_where_a_person_reads_them.py`, `tests/unit/test_R000_11__output_path_is_the_key_with_an_extension_appended.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract` over `INC-4821` in run `20260806T142203Z-4f1a` | `runs/20260806T142203Z-4f1a/extract/INC-4821.json`, byte-identical to the cache entry at `77c1b40a`, with `extract/INC-4821.meta.json` beside it (R0.3) |
| 2 | the same pipeline re-run unchanged as `20260907T090000Z-bbbb`, 0 model calls | `runs/20260907T090000Z-bbbb/extract/INC-4821.json` written too, identical bytes; a cache hit is still an output (R5.5) |
| 3 | the process killed while `verify` is running | `extract/` is complete under the run directory; each file is written as its document completes, not when the run ends (R4.1 row 4) |
| 4 | `INC-4821` failing validation twice (R6.9) | no `extract/INC-4821.json` and no `.meta.json`; the failure is on stdout and in the exit code, and nothing stands in for the artifact |
| 5 | a `report` step with no `output` declaration | `report/INC-4821.md`, the text the model returned |
| 6 | *counter-example* — `extract/INC-4821.json` deleted from `runs/` by hand, the pipeline re-run | a cache hit, 0 model calls; `runs/` is never read back, so nothing missing there is missing to `dossier` |
| 7 | *counter-example* — `dossier run --plan` | no `runs/<id>/` at all (R4.6) |
| 8 | the `report` step in `aggregate` mode, with no `output` declaration | `report/aggregate.md`; the one artifact filed under `*` (spec 003), named for what it is |

### R0.12 — `--replay` writes the reproduced artifacts to a new directory under the run, and writes nothing if any one of them cannot be reproduced

`runs/<run_id>/replays/<replay_id>/<step>/<document>.json`, named as R0.11
names them, with the provenance records beside them. A replay id has the form
of a run id. What the original run wrote is never touched: a replay is evidence
that the run still reproduces, and evidence that overwrote what it was checking
would be worth less.

All or nothing, because a partial tree would be the substitution R4.7 row 4
forbids: three of four documents rematerialised beside a manifest that pins
four reads as a complete run to anyone who did not see the error. The directory
is created only after every key has resolved.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run.replay`)
- **Proved by:** `tests/acceptance/test_R000_12__a_replay_writes_what_it_reproduced.py`, `tests/unit/test_R000_12__a_replay_directory_sits_under_its_run.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `runs/20260806T142203Z-4f1a/` holding only `manifest.json`, every key resolving | `runs/20260806T142203Z-4f1a/replays/20260918T140000Z-1e2f/extract/INC-4821.json` and the rest, byte-identical to the cache; stdout ends `3 artifact(s) reproduced · no model calls · written to runs/20260806T142203Z-4f1a/replays/20260918T140000Z-1e2f/` (R4.7) |
| 2 | the same run replayed twice | two directories under `replays/`, byte-identical to each other (R4.7) |
| 3 | `extract/INC-4821.json` under the run edited by hand, then the run replayed | the edited file is left as edited; the replay directory holds the cache bytes |
| 4 | *counter-example* — the cache entry for `INC-4822` absent, the other two present | exit 2 with the R4.7 row 4 error, and no `replays/<id>/` directory is created |
| 5 | *counter-example* — `dossier eval incident-audit --gold gold/incidents`, which reproduces the latest run through the same path | nothing written under `runs/`; eval reads a run, it does not add to one |
