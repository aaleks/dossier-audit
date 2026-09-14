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

## Rules and tests

Every spec ends with a numbered **Must hold** list. Each rule is an invariant, is
testable, and carries four fields — `Kind`, `Layer`, `Proved by`, `Status`. The
format and the checks are in `specs/README.md`; `/discover` writes them.

Rule ids are `R<spec>.<rule>`. Test files encode them:

```
tests/unit/test_R002_4__watermark_overlap_refetches_boundary_items.py
```

Two statuses exempt a rule from the named test having to exist, and both say so
rather than staying silent: `NOT MET` is the spec running ahead of the code, and
`SUPERSEDED by R2.10` is it running behind on purpose.

**Rule ids never move.** A rule that stops being true is superseded in place and
names its replacement; it is never renumbered, deleted, or rewritten to mean
something else. Test filenames and other rules cite those ids, and rewriting the
text under one leaves every test citing it claiming to prove something nobody
agreed to. `specs/README.md` has the procedure.

A pull request that changes a rule must change the matching test in the same PR.

## The two loops

```
OUTER   /accept ── one acceptance test, red ─────────────────▶ green, slice done
                      │                                 ▲
INNER                 └─ /tdd ─ /tdd ─ /tdd ─ /tdd ─────┘
                         one unit cycle each, suite green throughout
```

The **outer loop** is one acceptance test describing what a user of `dossier`
observes. It stays red for as long as the slice takes, so it carries
`@pytest.mark.outer_loop` and is excluded from the default run. "The suite is
green" and "the slice is unfinished" are both true at once, and neither is
confusing.

The **inner loop** is `/tdd`: one failing unit test driven to green with the
minimum code, then stop. The default suite is green at the end of every cycle.

**Exactly one outer loop is open at a time.** At most one rule may be
`IN PROGRESS`, and `tests/architecture/test_spec_coverage.py` checks that the
`outer_loop` marker sits on precisely that rule's test. When it goes green, the
marker comes off, the rule becomes `MET`, and the slice is done.

Currently open: **none**. Spec 006 is implemented: a step's `output` names a YAML
field declaration (R6.10, R3.10), and the stage key hashes both the declaration's
text (R6.11) and the JSON Schema generated from it (R6.12). `run --plan` refuses
a floating model alias at load time (R3.4). Next, as unit cycles: R0.6's named
list of undated pinned ids; R1.10 with the rest of R3.1 (its branch,
`tdd/R003_1-config-errors-name-file-line-key`, has row 1); then spec 009,
starting with R9.3. R7.2's outer loop waits for the gold files `_fixtures.md`
lists, which a person writes.

```bash
pytest                  # the default suite: offline, seconds, zero cost
pytest -m outer_loop    # the open slice. Red until it lands
pytest -m live          # the evaluated rules. Real model calls, run deliberately
```

## The skills

| Skill | Does | Then |
|---|---|---|
| `/discover` | Turns a request into rules with examples and counter-examples | `/accept` |
| `/accept` | Opens the outer loop: one failing acceptance test | `/tdd` |
| `/tdd` | One inner cycle: red, green, refactor, challenge, stop | `/tdd` again |
| `/eval` | The `evaluated` rules — a judge against an agreed threshold | — |
| `/verify` | Reads spec against test and asks whether it is really proved | — |
| `/quality` | Fans out to the agents, writes `quality-report.md` | — |

## Non-negotiable technical constraints

1. **Two packages reach the network, and no others.**
   `dossier.infrastructure.connectors` fetches source payloads;
   `dossier.infrastructure.models` asks a model. Nothing else may import a
   network client, on any code path, including a lazy import inside a function.
   This is R0.9 — it supersedes R0.1, which allowed only connectors and was
   already untrue of a tool whose stages ask a model. The boundary does not
   promise "no network"; it promises that everything right of it is
   reproducible, which is why a model is reached only on a cache miss and never
   during plan, replay or scoring. Checked by an `ast` walk over every module.
2. **No live model calls in the default test suite.** Tests use
   `FakeModelClient`, which returns canned responses and **counts calls** —
   several rules are claims about how many calls happened. An autouse fixture
   blocks sockets. The only exception is `tests/evals/`, marked `live`.
3. **Snapshots are immutable.** Never overwrite or delete a file under the
   snapshot store. New content means a new content-addressed path (R0.2).
4. **Determinism is testable.** Given the same snapshots, prompts, schemas and
   model identifier, the resolved plan and all cache keys must be byte-identical
   across runs and machines (R0.4, R5.6). No `hash()`, no unsorted set
   iteration, no absolute paths, no locale or timezone dependence. Sort before
   hashing; take the clock as an argument.

## Architecture

Two boundaries, described in `docs/architecture.md` and enforced by
`tests/architecture/`:

- **The hash boundary** — `infrastructure/connectors/` is the only package that
  may touch the network.
- **The purity boundary** — `domain/` imports the standard library and
  `pydantic`, and nothing else.

```
src/dossier/
  domain/          decisions: keys, resolution, normalisation, grounding, scoring
  application/     use cases: sync, convert, run, plan, eval
  infrastructure/  converters, store, ledger, model clients, tracking
    connectors/    the only package left of the hash boundary
  config/          sources.yaml, pipeline.yaml, credentials — the only reader of os.environ
  cli/             typer app — the only place sys.exit lives
```

**Default to `domain/`.** If a rule can be expressed as a pure decision, it goes
there: that is what makes it provable in milliseconds without a workspace, and
it is the only layer mutation testing can afford to run on. A decision sitting
in `infrastructure/` next to the call it guards is the most common decay in a
project like this, and no linter will find it.

## Stack

- Python 3.12+
- `pydantic` v2 for all schemas and configuration models
- `typer` for the CLI
- `pytest` for tests
- `mlflow` for run tracking, traces and judge scores (an optional extra; only
  `infrastructure/` may import it)
- YAML for `sources.yaml`, `pipeline.yaml` and the field declarations a step's
  `output` names. A pipeline is data end to end: `dossier` never imports an
  author's module to find out what they are extracting (R6.10)
- Connectors and converters registered via entry points, never hard-coded

No `langchain`. `dossier` calls models through its own `ModelClient` protocol in
`domain/ports.py`.

## Working style

- Small vertical slices over broad scaffolding. Prefer one path working
  end-to-end to ten modules that do not connect.
- Ask before inventing. If a spec is ambiguous, say so and propose wording.
  Never invent a threshold — ask, or record it as OPEN.
- Do not add dependencies without saying why in the commit message.
- Examples in specs use the values in `specs/_fixtures.md`. Do not invent a new
  incident key; add to that file.
