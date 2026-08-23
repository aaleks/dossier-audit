# 000 — Overview, vocabulary and global invariants

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

## Global invariants

**G1.** No component right of the hash boundary performs network I/O.

**G2.** Nothing under the snapshot store is ever modified or deleted in place.

**G3.** Every artifact produced by a stage has a sibling metadata record naming
its inputs by hash, the prompt version, the schema version, the model identifier
and the timestamp.

**G4.** Given identical inputs, the resolved manifest and every cache key are
byte-identical across runs and machines.

**G5.** Any state that determines an output is part of that output's cache key.
If changing something changes the result, changing it must invalidate the cache.

**G6.** Model identifiers are pinned exactly in configuration. Floating aliases
are rejected at config load time.

## Spec index

| Spec | Covers |
|---|---|
| `001-source-connectors.md` | The connector interface and its registration |
| `002-ledger-and-sync.md` | Change detection, incremental fetch, tombstoning |
| `003-pipeline-format.md` | `sources.yaml` and `pipeline.yaml` schemas |
| `004-step-resolution.md` | Reference expansion, the run manifest, plan diffing |
| `005-caching-and-keys.md` | Cache key composition, cascade, provenance records |
| `006-output-schemas.md` | Structured output, grounding, abstention, validation |
| `007-scoring-and-gold.md` | Gold sets, scorers, judge calibration, the change gate |
