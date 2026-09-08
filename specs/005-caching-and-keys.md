# 005 — Cache keys, cascade and provenance

**Status:** Partially implemented
**Rules:** R5.1 – R5.9

## Purpose

Make re-running cheap and make staleness impossible. Anything that can change an
output is part of that output's key (R0.5).

## Key composition

**Convert**

```
K_convert = H( snapshot_content_hash + converter_id + converter_version + options )
```

**Stage, per_file**

```
K_stage = H( prompt_hash + schema_hash + model_id + stage_options
             + sorted(input_artifact_hashes) )
```

**Stage, aggregate** — as above, over the sorted hashes of all input artifacts.

## Cascade

Because each key contains the hashes of its inputs, a change propagates
automatically:

```
snapshot ──▶ [convert] ──▶ [extract] ──▶ [verify] ──▶ [report]
                              K1           K2           K3
```

- edit the `verify` prompt → K2 changes → `verify` and `report` re-run,
  `extract` is served from cache
- one new document arrives → only that document flows through
- improve the PDF converter → everything re-converts, nothing re-downloads

## Provenance record

Every artifact has a sibling `<name>.meta.json`:

```json
{
  "step": "verify",
  "cache_key": "9f21c0a4",
  "inputs": [
    {"role": "documents", "path": "converted/INC-4821.md", "hash": "5d3ba0f7"},
    {"role": "extract",   "path": "extract/INC-4821.json", "hash": "77c1b40a"}
  ],
  "prompt": {"path": "prompts/02_verify.md", "hash": "0e52dd18"},
  "schema": {"path": "schemas/incident.json", "hash": "b81f0c6d"},
  "model": "anthropic:claude-sonnet-4-5-20250929",
  "run_id": "20260806T142203Z-4f1a",
  "dossier_version": "0.1.0"
}
```

### The root a path is relative to

Each path above is relative to a different root, and `role` is what says which.
A record whose paths all looked workspace-relative would be wrong in three
places at once, and `--replay` (R4.7) has to resolve every one of them years
later.

| `role` | Relative to |
|---|---|
| `prompt`, `schema` | the pipeline's own directory — a pipeline is self-contained and can be moved |
| `documents`, `reference` | the convert cache; the path is the artifact's name, not where its bytes are kept (spec 008) |
| a step id | that run's outputs |

No path is part of any key. Only hashes, identifiers and declared options are,
which is what makes R5.6 hold without anything needing to be normalised first.

## Must hold

### R5.1 — the provenance record and the cache key describe exactly the same inputs

Every input to a key appears in the record, and every entry in the record is part
of the key. The two are generated from one structure, so they cannot drift.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R005_1__provenance_and_key_cover_the_same_inputs.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the `verify` artifact for `INC-4821` | its record lists `5d3ba0f7`, `77c1b40a`, `0e52dd18`, `b81f0c6d` and the model, and the key is computed from those and nothing else |
| 2 | any single entry in the record perturbed | the recomputed key differs |
| 3 | an input added to the record but not to the key | rejected at construction; one structure produces both |
| 4 | *counter-example* — `run_id` and `dossier_version` in the record | present for provenance, excluded from the key; neither may change an output (R0.4) |

### R5.2 — changing a prompt changes that stage's key and every downstream key, and no upstream key

The cascade in one sentence.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R005_2__prompt_change_cascades_downstream_only.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `prompts/02_verify.md` edited | `verify` and `report` keys change |
| 2 | the same | the `extract` key is unchanged and `extract` is served from cache |
| 3 | the same | the convert keys are unchanged; nothing is re-converted and nothing is re-fetched |
| 4 | *counter-example* — trailing whitespace added to `prompts/02_verify.md` | the key changes; the prompt is hashed as bytes, and a "harmless" edit is not distinguishable from a real one |

### R5.3 — changing the model identifier changes every stage key

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R005_3__model_change_invalidates_every_stage.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the pinned model replaced with another exact pin | `extract`, `verify` and `report` keys all change |
| 2 | the same | convert keys are unchanged; conversion does not involve a model |
| 3 | the same | every artifact re-runs, which is what makes `--compare` a fair test (R7.8) |
| 4 | *counter-example* — the same model reached through a different endpoint or gateway | the identifier is unchanged, so keys are unchanged; the endpoint is not part of the answer |

### R5.4 — changing the converter version invalidates conversions and causes no re-fetch

The store is upstream of the converter, and improving a converter is not a reason
to touch the network.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R005_4__converter_version_invalidates_conversions_only.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the PDF converter version raised | every convert key changes; every document re-converts |
| 2 | the same, with the network stubbed to raise | the run completes; nothing is fetched |
| 3 | the same | every stage key changes too, because input artifact hashes changed (R5.2) |
| 4 | *counter-example* — the markdown converter version raised, in a pipeline with no markdown source | no key changes; only converters actually used are part of any key |

### R5.5 — a cache hit produces byte-identical output to the run that populated it

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R005_5__cache_hit_is_byte_identical.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `verify/INC-4821.json` produced, then the pipeline re-run unchanged | identical bytes; zero model calls |
| 2 | the same | the provenance record is present and identical (R0.3) |
| 3 | the cache populated on one machine and read on another | identical bytes; keys do not depend on the machine (R0.4) |
| 4 | *counter-example* — a stage whose output legitimately changed because an input changed | not a cache hit at all; a different key is a different entry |

### R5.6 — key computation is stable across machines, processes and Python versions

No `hash()`, no dict or set iteration order, no absolute paths, no locale, no
timezone. This is the rule the whole spec rests on, and every one of those five
has broken a cache in some project before.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R005_6__keys_are_stable_across_environments.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the `verify` key computed in two processes with different `PYTHONHASHSEED` | identical |
| 2 | the same computation from `/home/a/repo` and from `C:\repo` | identical; paths enter keys as repo-relative, with forward slashes |
| 3 | the same under `LC_ALL=tr_TR.UTF-8` and `TZ=Asia/Tokyo` | identical; no locale-cased or locale-formatted value is hashed |
| 4 | *counter-example* — two inputs supplied in a different order | identical, because input hashes are sorted before hashing; order is not information here |

### R5.7 — adding a document re-runs stages for that document only

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R005_7__new_document_reruns_only_itself.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4901` added to a source with 420 documents already cached | `extract` and `verify` run once each; 420 documents are served from cache |
| 2 | the same | the `report` step re-runs, because an `aggregate` step reads every input |
| 3 | the same, counted at the model client | exactly two `per_file` calls plus one `aggregate` call |
| 4 | *counter-example* — `INC-4901` added with bytes identical to an existing document | the same content hash, so the same key; even the new document is served from cache |

### R5.8 — an interrupted stage leaves no cache entry

A partially written artifact is never treated as a hit. Otherwise one interrupted
run poisons every run after it, and the symptom appears far from the cause.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R005_8__interrupted_stage_leaves_no_cache_entry.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the process killed while `verify/INC-4821.json` is being written | the next run recomputes it; no truncated file is read back |
| 2 | the process killed after the artifact is written, before its record | treated as a miss; an artifact without provenance is not a cache entry (R0.3) |
| 3 | a stage raising after two of five documents | those two are cached; the remaining three are not |
| 4 | *counter-example* — a document that failed validation twice | not an interruption; it is a recorded per-document failure and is deliberately not cached (R6.1, R6.9) |

### R5.9 — deleting the cache directory changes no output

The cache is an optimisation and never a source of truth. If deleting it changes
an answer, something is being remembered that should have been derived.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R005_9__cache_is_an_optimisation_only.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a run completed, the cache deleted, the same run repeated | byte-identical artifacts |
| 2 | the same | more model calls and more time; that is the only difference |
| 3 | a run with the cache deleted between two stages | completes; the later stage recomputes what it needs |
| 4 | *counter-example* — deleting the snapshot store rather than the cache | not covered; snapshots are inputs, not cache, and their loss is unrecoverable without a re-sync (R0.2) |
