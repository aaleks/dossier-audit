# Dossier — working agreement

`dossier` is a document collection and audit pipeline. It syncs documents from
configured sources, freezes them as immutable snapshots, converts them, runs a
sequence of prompt stages over them, and scores the results against a set of
human-verified answers.

Repository: `dossier-audit`. Package and CLI: `dossier`.

## The rule that governs this repository

**The specs in `specs/` are the source of truth. The code is an implementation
of them.**

- Behaviour that is not in a spec does not get implemented. If something is
  needed and unspecified, propose a spec amendment first and wait for review.
- When behaviour must change, the spec changes first, in its own commit. The
  code change follows in a second commit referencing it.
- Never patch code in a way that makes it diverge from its spec. If you find
  code and spec disagreeing, stop and report it — do not silently pick one.

## Must-hold rules and tests

Every spec ends with a numbered **Must hold** list. Each rule is testable and
each rule must be covered by at least one test.

Test naming: `test_R<spec>_<rule>__<description>`

```
tests/unit/test_R002_4__watermark_overlap_refetches_boundary_items.py
```

A pull request that changes a `Must hold` rule must change the matching test in
the same PR.

## Non-negotiable technical constraints

1. **No network outside the sync layer.** Nothing in convert, run, or eval may
   make a network call. This is what makes a run reproducible.
2. **No live model calls in the test suite.** Tests use a fake model client that
   returns recorded or canned responses. The suite must run offline, in seconds,
   at zero cost.
3. **Snapshots are immutable.** Never overwrite or delete a file under the
   snapshot store. New content means a new content-addressed path.
4. **Determinism is testable.** Given the same snapshots, prompts, schemas and
   model identifier, the resolved plan and all cache keys must be byte-identical
   across runs and across machines.

## Stack

- Python 3.12+
- `pydantic` v2 for all schemas and configuration models
- `typer` for the CLI
- `pytest` for tests
- `mlflow` for run tracking, traces and judge scores
- YAML for `sources.yaml` and `pipeline.yaml`
- Connectors and converters registered via entry points, never hard-coded

## Working style

- Small vertical slices over broad scaffolding. Prefer one path working
  end-to-end to ten modules that do not connect.
- Ask before inventing. If a spec is ambiguous, say so and propose wording.
- Do not add dependencies without saying why in the commit message.
