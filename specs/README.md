# Specifications

The specs here are the source of truth. The code is an implementation of them.

Read `000-overview.md` first: it holds the vocabulary, the hash boundary, the
hash algorithm, the workspace layout, and the eight global invariants every other
spec assumes.

| Spec | Covers | Rules | Status |
|---|---|---|---|
| `000-overview.md` | Vocabulary, the hash boundary, hashing, workspace layout, global invariants | R0.1 – R0.14 | Implemented |
| `001-source-connectors.md` | The connector interface and its registration | R1.1 – R1.13 | Implemented |
| `002-ledger-and-sync.md` | Change detection, incremental fetch, tombstoning, the store | R2.1 – R2.22 | Implemented |
| `003-pipeline-format.md` | `sources.yaml` and `pipeline.yaml` schemas | R3.1 – R3.13 | Implemented |
| `004-step-resolution.md` | Reference expansion, the run manifest, plan diffing | R4.1 – R4.14 | Implemented |
| `005-caching-and-keys.md` | Cache key composition, cascade, provenance records | R5.1 – R5.10 | Implemented |
| `006-output-schemas.md` | Structured output, grounding, abstention, validation | R6.1 – R6.16 | Implemented |
| `007-scoring-and-gold.md` | Gold sets, scorers, judge calibration, the change gate | R7.1 – R7.25 | Implemented |
| `008-conversion.md` | The converter interface, its registration, versioning and selection | R8.1 – R8.12 | Implemented |
| `009-model-providers.md` | Model providers, their pinned forms, and where each is reached | R9.1 – R9.16 | Implemented |
| `010-mlflow-tracking.md` | MLflow tracking: the switch, experiment routing, and what tracking may not do | R10.1 – R10.8 | Implemented |
| `011-tracking-records.md` | What each command records to MLflow: runs, traces, spans and metrics | R11.1 – R11.7 | Partially implemented |
| `012-evaluation-datasets.md` | Publishing a gold set as an MLflow evaluation dataset, and the eval run that links to it | R12.1 – R12.6 | Partially implemented |

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
| `SUPERSEDED by RN.x` | No longer true. Kept in place for its id and its history. |

## Retiring a rule

**A rule is never renumbered, rewritten to mean something else, or deleted.** Its id
is referenced by test filenames and by other rules, so all three break links silently
— and the worst of them is rewriting the text, because every test citing that id then
claims to prove something nobody agreed to.

When behaviour changes, add the new rule at the end of its spec and mark the old one:

```markdown
- **Status:** SUPERSEDED by R2.10
```

The old rule keeps its examples. They are the record of what was true before and why
it changed, which is the question anyone re-reading the spec in a year will have.
`test_spec_coverage.py` checks that the replacement exists, is not the rule itself,
and is not in turn superseded — a reader following the trail lands on the rule that is
in force today.

A superseded rule is exempt from naming a test that exists, like `NOT MET`. Its old
test should be deleted or reclaimed by the replacement; the "every test file is claimed
by a rule" check will catch it if neither happened.

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
