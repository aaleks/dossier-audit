# 005 — Cache keys, cascade and provenance

**Status:** Partially implemented
**Rules:** R5.1 – R5.12

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
K_stage = H( prompt_hash + schema_hash + generated_schema_hash + model_id
             + stage_options + sorted(input_artifact_hashes) )
```

`schema_hash` is the hash of the field declaration a step's `output` names, taken
over its text (R6.11). `generated_schema_hash` is the hash of the JSON Schema
generated from it and shown to the model, taken over canonical JSON (R6.12). A
step with no `output` has neither.

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
  "schema": {"path": "schemas/incident.yaml", "hash": "6e0d4b27"},
  "generated_schema": {"hash": "d24c86e1"},
  "model": "anthropic:claude-sonnet-4-5-20250929",
  "run_id": "20260806T142203Z-4f1a",
  "dossier_version": "0.1.0"
}
```

### An entry that is present and unreadable

R5.9 names deletion, which correctly misses and recomputes. The neighbouring case
is an entry that is *there* and cannot be read — truncated by an interrupted
write on a filesystem that did not honour the rename, or edited by hand.

It is never authority. What it is instead depends on who asked, and the two
answers are different because their options are:

| Caller | A damaged entry is | Because |
|---|---|---|
| `run` | a miss | the inputs are all still present, so the work can simply be redone and the entry rewritten. Aborting would make one corrupt file permanently fatal to a healthy workspace |
| `--replay` | fatal, naming the entry | a replay has no model and nowhere to put one. Serving the bytes would present something other than what the run produced, and recomputing would be the substitution R4.7 row 4 forbids |

The failure this closes was not the corruption but the report of it. Because
pydantic's `ValidationError` subclasses `ValueError`, an unreadable entry
propagated out of execution and was caught by the handler for *resolution*
failures — which prints that nothing ran and nothing was written, after the
manifest had been written and earlier stages had run.

### How a text file is hashed

A prompt, a schema and a `pipeline.yaml` are hashed over their decoded text with
line endings normalised. A fetched payload is not: a snapshot is hashed exactly
as received (R1.2, R2.10), because translating newlines there would change the
content hash of every file it touched and make the store lie about what it holds.

The distinction is content versus configuration, and it is one named function
rather than a convention each call site follows. `pipeline_hash` was taken over
raw bytes while prompt hashes were taken over decoded text, so the same
`pipeline.yaml` hashed two ways depending on whether the checkout used CRLF — and
a workspace is the user's own directory, which `dossier` does not control and
which may have no `.gitattributes`. The failure is silent rather than wrong: a
team with a Windows checkout and Linux CI never matches a manifest, so `--plan`
reports every step as new forever and the cache is paid for and never used.

**Normalising line endings is not normalising content.** R5.2's counter-example
still holds exactly as written: trailing whitespace, a changed word and a
reordered key all move the hash. Its phrase "hashed as bytes" means the file is
not interpreted or reformatted — not that a checkout convention is allowed to
change a key.

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
| 5 | *counter-example* — `attempts` in the record of `verify/INC-4821.json`, written on the second try | present for provenance (R6.2 row 1), excluded from the key; a retried answer that validated is the same answer, and an artifact is never re-derived because the road to it was longer |

### R5.2 — changing a prompt changes that stage's key and every downstream key, and no upstream key

The cascade in one sentence.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R005_2__prompt_change_cascades_downstream_only.py`
- **Status:** MET

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
| 2 | the same computation from `/home/a/repo` and from `C:\repo` | identical; no path enters a key at all, so there is nothing for a working directory to change |
| 3 | the same under `LC_ALL=tr_TR.UTF-8` and `TZ=Asia/Tokyo` | identical; no locale-cased or locale-formatted value is hashed |
| 4 | *counter-example* — two inputs supplied in a different order | identical, because input hashes are sorted before hashing; order is not information here |

### R5.7 — adding a document re-runs stages for that document only

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R005_7__new_document_reruns_only_itself.py`
- **Status:** SUPERSEDED by R5.10

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

### R5.10 — adding a document re-runs stages for that document only, and no two documents share a stage key

Supersedes R5.7, whose first three rows are restated here unchanged and whose
fourth is no longer true. R5.7 row 4 said that a document added with bytes
identical to one already held hashed the same and was served from the same cache
entry. R3.13 puts the document's key inside the value handed to the prompt, so
identical bytes under two keys are now two values, two hashes and two keys, and
the model is asked once per document.

That reads like a saving lost, and it is the opposite. A stage is asked about a
*named* document and answers with that name in `source.document` (R6.3). Two
documents sharing one entry therefore shared one answer, and the answer named
whichever of them was computed first: `runs/<id>/extract/INC-9999.json` held
`"document": "INC-4821"`, with every span cited against `INC-4821` too. Nothing
caught it, because both documents are inputs to the same stage and the citation
resolved -- it was simply attributed to the wrong one. `_from_cache` said so in a
comment and accepted it, because under R5.7 there was nothing else it could do:
re-serialising the artifact under this document's name would have handed the next
step bytes the cache never held, and changed its key.

The saving was never real either. Where the duplicate is an artefact of a source
listing the same document twice, sync gives it one key and there is nothing to
re-run. Where it is genuinely two documents that happen to read alike -- two
incidents filed from one template -- they are two documents, and a report that
said so once and attributed it to one of them was wrong.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R005_10__a_new_document_reruns_only_itself_and_keys_are_per_document.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4901` added to a source with 420 documents already cached | `extract` and `verify` run once each; 420 documents are served from cache |
| 2 | the same | the `report` step re-runs, because an `aggregate` step reads every input |
| 3 | the same, counted at the model client | exactly two `per_file` calls plus one `aggregate` call |
| 4 | `INC-4901` added with bytes identical to an existing document | a different key, and one model call; the value hashed holds `<document key="INC-4901">` and no other document's value does (R3.13) |
| 5 | the artifact that call produced | `extract/INC-4901.json` says `"document": "INC-4901"`; under R5.7 it said `"document": "INC-4821"` and was filed under `INC-4901` regardless |
| 6 | *counter-example* — the same document listed twice by one source | one key from sync, so one document and nothing to re-run; this rule is about two keys, not two listings (R2.1) |
| 7 | *counter-example* — the same document, unchanged, on a second run | served from cache, no model call; a key is per document and still not per run (R5.5) |

### R5.11 — a provenance record says how many tokens its artifact cost, summed over its attempts, and no key holds them

`attempts` already sat in the record beside the key and outside it (R5.1 row
5): the road to an answer is worth recording and is no part of what the answer
is. What the road cost belongs beside it, for the same reason and on the same
terms. The record gains `"tokens": {"input": ..., "output": ...}`, the sum of
what every attempt's reply said it cost (R9.18).

An attempt that failed validation cost as much as the one that stood, so it is
in the sum. A count one attempt did not give makes that side of the sum `null`:
a total over the attempts that reported would read as the whole.

A cache hit copies the record it was stored with (R0.3 row 2), so a record says
what it cost to *produce* the artifact, not what any later run paid to read
it -- which was nothing, and R5.12 is where that is said.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys.provenance`, `dossier.domain.usage`), application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R005_11__a_provenance_record_says_what_its_artifact_cost.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `verify` over `INC-4821`, valid on its first attempt, which cost 1204 in and 212 out | `verify/INC-4821.meta.json` holds `"tokens": {"input": 1204, "output": 212}` beside `"attempts": 1` |
| 2 | `INC-4822` valid on its second attempt, the two costing 1204/212 and 1391/230 | `"tokens": {"input": 2595, "output": 442}`; the refused attempt is in the sum |
| 3 | the same artifact served from cache in run `20260907T090000Z-bbbb` | the record byte-identical to the one written in `20260806T142203Z-4f1a`: the cost of producing it, not of reading it |
| 4 | a provider that reports nothing (R9.18 row 4) | `"tokens": {"input": null, "output": null}` |
| 5 | the first attempt reported, the second not | `null` on each side the second did not give; a partial sum is not the sum |
| 6 | *counter-example* — the same inputs answered again at another token count | the same key; tokens are what an answer cost, not what it was asked (R0.5, R5.1 row 5) |
| 7 | *counter-example* — a document that failed validation twice | no artifact and no record (R0.3 row 3); what it cost is still spent, and R5.12 row 4 counts it |

### R5.12 — `dossier run` says how many tokens each step spent, and a document served from cache spent none

Each step's line ends with what its model calls cost in this run:

```
extract: 3 document(s) · 0 from cache · 0 failed · 3,612 tokens in · 636 out
```

This is the figure a cache exists to keep small, and the first time it can be
seen: a re-run prints the same line with `3 from cache` and no tokens at all.
The clause is absent for a step that asked no model, for the reason `described`
and `findings` are absent at zero (R6.15, R6.16): it would be on every line of
every cached run. A step with a call whose provider did not say what it cost
ends `· tokens not reported`, never `· 0 tokens in` (R9.18 row 4).

Composed by `step_line`, so the description of the record the run closes says
the same (R11.17). The thousands separator is `,` whatever the locale: Python's
`,` format is not locale-aware, which is what keeps two machines' lines
identical (R0.4).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.step_line`), application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R005_12__a_run_says_what_each_step_spent.py`, `tests/unit/test_R005_12__the_step_line_says_what_was_spent.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | three documents, nothing cached, each answer costing 1204 in and 212 out | `extract: 3 document(s) · 0 from cache · 0 failed · 3,612 tokens in · 636 out` |
| 2 | the same run again, every document served from cache | `extract: 3 document(s) · 3 from cache · 0 failed` and nothing about tokens: nothing was asked, so nothing was spent |
| 3 | only `INC-4822` changed since | `· 1,204 tokens in · 212 out`: the one document that was asked |
| 4 | `INC-4822` failing validation twice, each attempt 1204/212 | its 2,408 in and 424 out are in the step's total; spent, though nothing was written |
| 5 | *counter-example* — a provider that reports nothing | `· tokens not reported`, not `· 0 tokens in` |
| 6 | *counter-example* — `dossier run --plan` | no tokens anywhere: planning asks no model (R4.6) |
