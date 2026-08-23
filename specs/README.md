# Specifications

The specs here are the source of truth. The code is an implementation of them.

Read `000-overview.md` first: it holds the vocabulary, the hash boundary and the
six global invariants every other spec assumes.

| Spec | Covers | Rules | Status |
|---|---|---|---|
| `000-overview.md` | Vocabulary, the hash boundary, global invariants | R0.1 – R0.6 | Proposed |
| `001-source-connectors.md` | The connector interface and its registration | R1.1 – R1.9 | Proposed |
| `002-ledger-and-sync.md` | Change detection, incremental fetch, tombstoning | R2.1 – R2.9 | Proposed |
| `003-pipeline-format.md` | `sources.yaml` and `pipeline.yaml` schemas | R3.1 – R3.8 | Proposed |
| `004-step-resolution.md` | Reference expansion, the run manifest, plan diffing | R4.1 – R4.9 | Proposed |
| `005-caching-and-keys.md` | Cache key composition, cascade, provenance records | R5.1 – R5.9 | Proposed |
| `006-output-schemas.md` | Structured output, grounding, abstention, validation | R6.1 – R6.9 | Proposed |
| `007-scoring-and-gold.md` | Gold sets, scorers, judge calibration, the change gate | R7.1 – R7.12 | Proposed |

Supporting files:

| File | Purpose |
|---|---|
| `_template.md` | The rule format. `/discover` copies this to start a new spec. |
| `_fixtures.md` | The canonical example values every spec's tables draw from. |

## Status values

**Spec status** — the header of each file.

| Value | Meaning |
|---|---|
| `Proposed` | Written, not built. What `/discover` produces. |
| `Partially implemented` | Some rules are `MET`, others are not. |
| `Implemented` | Every rule is `MET`. |

**Rule status** — the `**Status:**` line of each rule.

| Value | Meaning |
|---|---|
| `NOT MET` | Written, not built. No test needs to exist yet. |
| `IN PROGRESS` | The open outer loop. Its acceptance test exists and is red. At most one rule repository-wide. |
| `MET` | The named test exists and passes in the default suite. |

## The shape of a rule

Every rule is parsed by `tests/architecture/test_spec_coverage.py`, so the shape
is load-bearing rather than stylistic:

```markdown
### R2.4 — sync asks from `last_sync_at` minus an overlap

<the invariant, in one or two sentences>

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.window_start`)
- **Proved by:** `tests/unit/test_R002_4__watermark_overlap_refetches_boundary_items.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `last_sync_at=2026-08-06T09:00:00Z`, default overlap | `since = 2026-08-05T09:00:00Z` |
| 2 | *counter-example* — a source that has never synced | `since = None`; the overlap has nothing to subtract from |
```

The checker enforces: `Kind` is `deterministic` or `evaluated`; `Proved by`
names a test path; an `evaluated` rule carries a `Threshold` (a number and who
agreed it, or `OPEN`); every rule has an example table with at least one
counter-example; a rule that is not `NOT MET` names a test file that exists; and
every test file is claimed by some rule.

Rule ids are stable. Tests reference them in filenames and docstrings, so
renumbering silently breaks that link.
