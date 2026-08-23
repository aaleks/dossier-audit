---
name: accept
model: claude-sonnet-5
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
description: Open the OUTER loop - write the one failing acceptance test for a spec rule, before any implementation exists. Use after /discover has agreed a spec, or when a slice has no acceptance test yet. Second step of the SDD loop; /tdd then drives it to green from the inside.
argument-hint: "<rule id> [spec file]"
---

Open the outer loop for: $ARGUMENTS

The rule is written. This turns it into **one failing acceptance test** that describes
what a user of `dossier` observes — and then stops.

The failing test is the deliverable. Do not write production code in this skill.

## The two loops

```
OUTER   /accept  ─────────── one acceptance test, red ───────────▶ green, slice done
                      │                                    ▲
INNER                 └─ /tdd ─ /tdd ─ /tdd ─ /tdd ─ /tdd ─┘
                         one unit cycle each, all green throughout
```

The outer test stays red for as long as the slice takes. That is not a broken build:
it carries `@pytest.mark.outer_loop`, which `pyproject.toml` excludes from the default
run. The default suite stays green the whole time; the outer loop is run deliberately
with `pytest -m outer_loop`.

**At most one outer loop is open at a time.** `tests/architecture/test_spec_coverage.py`
enforces it, in both directions: at most one rule may be `IN PROGRESS`, and the
`outer_loop` marker must be on exactly that rule's test. Two open slices is how neither
gets finished.

## First: check the rule is ready

Look at its fields in the spec.

- `**Kind:** deterministic` — continue.
- `**Kind:** evaluated` — **stop.** An evaluated rule cannot have an exact test;
  asserting on generated prose produces a flake that gets deleted in three weeks. Send
  the user to `/eval`, and offer to take the next deterministic rule instead.
- Kind missing — the spec is unfinished. Send the user back to `/discover`.

Then check nothing else is already open:

```bash
grep -rn "IN PROGRESS" specs/
```

If a rule is already `IN PROGRESS`, say so and stop. Finishing that slice comes first.

**One rule per invocation.** Do not write tests for rules the user did not name.

## Why the test comes first

A test written after the code tends to assert what the code happens to do. A test
written from the spec asserts what was agreed. When they differ, that difference is the
finding — and you only see it if the test came first.

Watching it fail matters just as much. A test that has never been red has never been
shown capable of failing.

## 1. Read the rule, not the code

Open the spec. Take one rule. Its example table is your test cases — the values are
concrete precisely so they can be transcribed, and they come from `specs/_fixtures.md`
so the same `INC-4821` means the same thing in every test in the repo.

Do not read the implementation first. If it exists, it will bias the test toward what
it does.

## 2. Choose the rule worth an outer loop

Not every rule deserves one. An outer loop is right when the rule is **observable from
the CLI and needs more than one component to be true**. R2.5 is the model: it cannot be
satisfied by the connector alone, or the store alone, or the ledger alone.

| The rule is | Tier | Directory |
|---|---|---|
| observable from the CLI, spans components | acceptance — **the outer loop** | `tests/acceptance/` |
| a `domain/` decision | unit | `tests/unit/` |
| about config loading or wiring | integration | `tests/integration/` |

If the rule you were given is a pure `domain/` decision, say so: it wants a unit test
and belongs to `/tdd` directly, with no outer loop of its own. Write the unit test here
and set the rule's status to `NOT MET` still — the status only becomes `IN PROGRESS`
for an open acceptance loop.

## 3. Write it

The file is named for the rule: `tests/acceptance/test_R002_5__second_sync_fetches_nothing.py`.
One class per rule, named after the rule. One test per example row.

```python
pytestmark = pytest.mark.outer_loop


class TestSecondSyncIsFree:
    """R2.5 — the observable promise of incremental sync."""

    def test_second_sync_reports_no_work(self, workspace):
        """The one where nothing changed, so nothing should happen."""
```

Naming:

- The test name states the **business rule**, not the mechanism:
  `test_a_changed_document_is_the_only_one_refetched`, never `test_sync_2`.
- The class docstring quotes the rule with its id.
- **Include the counter-example.** It is a test too, and in this project it is usually
  the only thing standing between a real test and one a stub returning zero would pass.

Hard constraints:

- **No real model call.** Use `fake_model`, or `no_model` for the rules that permit
  none. **Assert the call count** — R2.5, R4.6, R5.5 and R5.7 are claims about how many
  calls happened, and a canned response proves nothing about them.
- **No network.** The autouse `no_network` fixture blocks sockets; do not disable it.
- Use the `workspace` fixture rather than writing into `tests/fixtures/`.
- **If you cannot inject a fake, the production code has a seam problem.** Say so and
  stop. Do not reach for `unittest.mock.patch` to paper over it — that hides the design
  problem and produces a test coupled to internals.
- Import the not-yet-existing production module **inside** the helper, not at module
  scope, so collecting the default suite does not error on a package that has no code
  in it yet.

## 4. Run it and read the failure

```bash
uv run pytest -m outer_loop -q
```

It must fail. Then check **why**:

| Failure | Meaning |
|---|---|
| `ModuleNotFoundError` / `ImportError` | Correct — nothing implements it yet. Proceed. |
| `AssertionError` with a plausible value | Something already does this. Stop and tell the user: the spec may be describing existing behaviour, which changes the job. |
| It passes | The test is wrong — it asserts something trivially true. Rewrite it. |

A test that passes before implementation is the failure mode to watch for.

## 5. Close the loop on the spec

Update the rule in the spec:

- `**Proved by:**` — the real test path
- `**Status:**` — `IN PROGRESS`

Then:

```bash
uv run pytest tests/architecture -q
```

That must pass. It checks that the reference resolves, that this is the only rule
`IN PROGRESS`, and that the `outer_loop` marker is on exactly this rule's test. A typo
or a marker on the wrong file fails here, which is what makes the link real rather than
decorative.

## Report

State, in this order:

1. The rule id, the file and the test names written.
2. The **exact** failure message.
3. Why that failure is the correct red.
4. The first inner cycle you would take — usually the smallest `domain/` decision the
   acceptance test needs.

Then stop. `/tdd` drives it from the inside, one unit test at a time.
