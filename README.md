# dossier-audit

Document collection and audit pipeline. Syncs documents from configured sources,
freezes them as immutable snapshots, runs a sequence of prompt stages over them,
and scores the results against human-verified answers.

Package and CLI: `dossier`.

**Status: specification complete, implementation not started.** 71 rules across 8
specs, one open acceptance test, no production code yet. That is deliberate — see
"How this is built" below.

## Layout

| Path | What |
|---|---|
| `specs/` | The source of truth. Start at `specs/000-overview.md`, then `specs/README.md` for the index. |
| `CLAUDE.md` | The working agreement for this repository |
| `docs/architecture.md` | The two boundaries and the layer contracts |
| `docs/dossier-design-deck.pdf` | Background: the proposal this came from |
| `src/dossier/` | The package. Layer skeleton only, so far. |
| `tests/` | `architecture/`, `unit/`, `acceptance/`, `integration/`, `evals/` |
| `KICKOFF.md` | Prompt for the first implementation session |
| `.claude/` | The spec-driven toolchain: skills, agents, rules, hooks |

## Commands (target shape)

```
dossier sync <pipeline>              # fetch only what changed
dossier run <pipeline> --plan        # what would run, and why
dossier run <pipeline>               # execute
dossier eval <pipeline> --gold …     # score against verified answers
dossier eval <pipeline> --compare a b
dossier run --replay runs/<id>/      # reproduce a past run exactly
```

## How this is built

Specification-driven, with a double TDD loop. The specs come first and the code
implements them; a rule that is not in a spec does not get built.

```
/discover ──▶ /accept ──▶ /tdd ─ /tdd ─ /tdd ──▶ /verify ──▶ /quality
   spec        outer         inner cycles          audit       report
               loop
```

- The **outer loop** is one failing acceptance test describing what a user
  observes. It carries `@pytest.mark.outer_loop` and stays red while the slice is
  built. Exactly one is open at a time, and the test suite enforces that.
- The **inner loop** is one unit test at a time, driven to green with the minimum
  code. The default suite is green at the end of every cycle.

Currently open: **R2.5** — "a second sync with nothing changed fetches zero
payloads and writes zero snapshots".

## Running the tests

```bash
uv sync                 # or: python -m venv .venv && pip install -e ".[dev]"

pytest                  # the default suite: offline, seconds, zero cost
pytest -m outer_loop    # the open slice. Red until it lands
pytest -m live          # the evaluated rules. Real model calls, run deliberately
```

The default suite blocks network access outright — an autouse fixture refuses
socket creation for any test not marked `live`. That is not test hygiene, it is
R0.1: nothing right of the hash boundary touches the network, which is what makes
a run from six months ago reproducible.

`pytest tests/architecture` is the mechanical half of the working agreement. It
checks the hash boundary, the layer contracts, and that every spec rule and every
test file still refer to each other.
