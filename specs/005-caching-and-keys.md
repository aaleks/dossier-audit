# 005 — Cache keys, cascade and provenance

## Purpose

Make re-running cheap and make staleness impossible. Anything that can change an
output is part of that output's key.

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
  "cache_key": "9f21c0…",
  "inputs": [
    {"role": "documents", "path": "converted/INC-4821.md", "hash": "a3f9c1e2"},
    {"role": "extract",   "path": "extract/INC-4821.json", "hash": "77c1b40a"}
  ],
  "prompt": {"path": "prompts/02_verify.md", "hash": "0e52dd18"},
  "schema": {"path": "schemas/incident.json", "hash": "b81f0c6d"},
  "model": "anthropic:claude-sonnet-4-5-20250929",
  "run_id": "2026-08-23T14:22:03Z-4f1a",
  "dossier_version": "0.1.0"
}
```

## Must hold

**R5.1** Every input to a cache key is recorded in the corresponding provenance
record, and every entry in that record is part of the key.

**R5.2** Changing a prompt file changes that stage's key and every downstream
key, and no upstream key.

**R5.3** Changing the model identifier changes every stage key.

**R5.4** Changing the converter version invalidates conversions but does not
cause any re-fetch.

**R5.5** A cache hit produces byte-identical output to the run that populated it.

**R5.6** Key computation is stable across machines, processes and Python
versions: no `hash()`, no dict iteration order, no absolute paths, no locale or
timezone dependence.

**R5.7** Adding a document to a source re-runs stages for that document only.

**R5.8** An interrupted stage leaves no cache entry. A partially written artifact
is never treated as a hit.

**R5.9** Deleting the cache directory changes no output — only the time taken.
