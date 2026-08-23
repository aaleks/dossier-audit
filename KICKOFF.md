# Kickoff — the first implementation session

The setup is done. The specs are written, the toolchain is adapted, the
architecture tests pass, and the first acceptance test is red and waiting.

Paste everything below into a fresh session at the repo root.

---

Read `CLAUDE.md`, `docs/architecture.md` and `specs/002-ledger-and-sync.md`
before writing anything. `specs/` is the source of truth; the code is an
implementation of it.

The outer loop is already open:

```bash
pytest -m outer_loop
# tests/acceptance/test_R002_5__second_sync_fetches_nothing.py
# ModuleNotFoundError: No module named 'dossier.cli.main'
```

**R2.5** — a second sync with nothing changed fetches zero payloads and writes
zero snapshots. Your job is to close it with `/tdd`, one inner cycle at a time.

Before the first cycle:

1. List anything in specs 001, 002 and 003 that is ambiguous, contradictory or
   missing for the slice below. Propose exact wording for each. Wait for my
   answer — do not invent, and do not start.
2. Propose the modules you expect to add, one line each, and which layer each
   belongs to. No code yet.

Once I have replied, work the loop. Each `/tdd` invocation is **one** unit test
driven to green with the minimum code, then stop and report. The default suite
stays green at the end of every cycle; the acceptance test stays red until the
slice lands.

## What R2.5 needs, roughly

Every one of these is already specified. Take them in whatever order the failing
assertions demand, and write the unit test from the rule's example table first:

- `folder` connector — `list`, `fetch`, `attachments` (R1.2, R1.3, R1.5)
- content-addressed snapshot store (R0.2)
- the ledger and its rows (spec 002)
- the normalisation projection and the change decision (R2.2, R2.3)
- the sync window (R2.4)
- `sources.yaml` loading and validation (R3.1, R3.8)
- `dossier sync` in `cli/`, printing what it did

Each of those rules has a `Proved by:` path already named in the spec. Write the
test at that path, then set the rule's `Status:` to `MET` when it is green.

## Explicitly out of scope for this slice

Jira, Confluence, PDF conversion, page images, MLflow, LLM judges, real model
calls, `run`, `--plan`, `eval`. They have rules; they are not this slice.

## Definition of done

- `pytest -m outer_loop` passes
- the `outer_loop` marker is removed from the acceptance test, so it joins the
  default suite
- R2.5's `Status:` is `MET`, and so is every rule you proved on the way
- `pytest` passes offline, with no network and no model calls, in seconds
- `pytest tests/architecture` passes — including the check that no rule is left
  `IN PROGRESS` with a marker on the wrong file

Then run `/verify`, and `/quality` before the PR.

## If a spec is wrong

Stop and say so. Do not patch the code around it and do not quietly edit the
rule. The spec changes first, in its own commit, and the code follows in a second
commit referencing it. A disagreement between spec and code is the finding, not
an obstacle.
