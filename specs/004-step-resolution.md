# 004 — Step resolution and the run manifest

## Purpose

Relative references make configuration pleasant to write and dangerous to
execute. This spec removes the danger by expanding them once, before any work
starts, and freezing the result.

## Two phases

```
pipeline.yaml                          manifest.json
─────────────                          ─────────────
- id: extract                          extract  <- [documents]
  input: documents
- id: verify          ══ resolve ══>   verify   <- [documents, extract]
  input: previous
- id: report                           report   <- [verify]
  input: previous
```

After resolution the word `previous` does not exist anywhere in the system.
Execution reads only concrete ids.

## The manifest

Written to `runs/<run_id>/manifest.json` before the first stage executes:

- pipeline name and the hash of `pipeline.yaml`
- every step with its **expanded** input ids
- the exact snapshot content hashes pinned for this run
- prompt file hashes, schema hashes, converter versions
- the pinned model identifier
- `dossier` version and run start time

## Plan diffing

`dossier run <pipeline> --plan` resolves the pipeline, compares it against the
most recent manifest for that pipeline, and prints per step: `cached`,
`prompt changed`, `inputs changed`, `upstream changed`, or `new`. It executes
nothing.

Inserting a step between two others re-points the relative references below it.
That is a real change to the graph and appears in the diff:

```
! verify: inputs changed
      was: [documents, extract]
      now: [documents, enrich]
  -> cache invalid, will re-run (and report after it)
```

## Replay

`dossier run --replay runs/<run_id>/` executes from that run's frozen manifest
and ignores the current `pipeline.yaml` entirely.

## Must hold

**R4.1** Resolution completes fully before any stage executes; a resolution error
means nothing runs.

**R4.2** `previous` expands to the immediately preceding step id; `previous(n)`
expands to the `n` preceding step ids in declaration order.

**R4.3** `previous` in the first step, or `previous(n)` where `n` exceeds the
number of preceding steps, is an error.

**R4.4** The manifest contains only concrete ids. No relative reference survives
resolution.

**R4.5** Reordering or inserting steps changes at least one resolved input list,
and that change appears in `--plan` output before anything executes.

**R4.6** `--plan` performs no model calls, writes no outputs, and leaves the cache
untouched.

**R4.7** `--replay` reproduces a past run's outputs byte-for-byte and performs no
network I/O, regardless of the current configuration on disk.

**R4.8** Resolving the same pipeline twice produces a byte-identical manifest
apart from the run id and start time.

**R4.9** A run whose pinned snapshots have since been superseded still resolves
and replays; the newer snapshots are ignored.
