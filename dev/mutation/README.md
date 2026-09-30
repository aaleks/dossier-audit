# Mutation testing over `domain/`

A mutant is the code with one small change: a `<` made `<=`, a `continue`
made `break`, a `0` made `1`. A test that fails is said to kill the mutant. A
mutant that nothing kills survives, and a survivor is usually one of two
things:

- a boundary no example row sits on;
- a line no assertion reads.

`mutation.toml` fixes the scope at `src/dossier/domain`, and says why.

```bash
uv sync --locked --all-extras --no-extra docling --group mutation
python dev/mutation/mutate.py init      # about 10 minutes
python dev/mutation/mutate.py run       # about 3 hours on 14 workers; resumable
python dev/mutation/mutate.py report
```

Run these with the project's own interpreter (`.venv/Scripts/python.exe` on
Windows, where `uv run` can be refused).

## Why not `cosmic-ray exec`

cosmic-ray lists the mutants and applies them. Its own runner would try each
one against `pytest tests/unit`, about 90 seconds a time, and `domain/` gives
about 7,400 mutants: a week. This runner cuts that three ways:

1. **It drops mutants no test could see**, before running any:
   - one that does not compile;
   - one whose only change is inside a type annotation (every domain module has
     `from __future__ import annotations`);
   - three shapes the first run found never observable: `*,` in a signature
     made `/,`, `frozen=True` made `False`, and `==` swapped with `is`.

   About 4,000 are left.
2. **It runs each mutant against the tests that execute its lines, and no
   others.** `init` runs the default suite once under coverage, recording
   which test ran each line. Unit tests go first, and at most 120 run for a
   mutant (`--cap`).
3. **It runs in parallel copies of the repository**, rebuilt at every start.
   The repository itself is never changed. `.env` is never copied.

Everything goes in `%TEMP%\dossier-mutation` (`--work` to move it):

- `c<k>`: the copies;
- `coverage.data`: the line-to-test map;
- `mutants.json`: the mutants, and a hash of each module they were counted in;
- `results.jsonl`: one line per mutant tried.

## Reading a survivor

Confirm it before writing anything for it. The method has two ways of calling
a mutant a survivor when it is not:

- **Capped.** Its lines ran more than 120 tests, and the ones that would kill
  it may be past the cap. `report` says so. Try it again in full:
  `run --only scoring.py:545 --cap 0`.
- **In a class body.** A pydantic `Field(...)` or a dataclass default runs at
  import, and line coverage does not see a test that only builds the model. In
  the first run, `repr=False` on MLflow's secrets looked alive, and R10.16's
  test kills it.

After a test is written, try the mutant again with `--suite`. The coverage map
has not seen the new test, so the selection cannot include it, and `--suite`
runs the whole default suite instead:
`run --only scoring.py:545 --suite`.

A survivor that holds up is one of three things:

- **A row nobody wrote.** The spec gets the row first, then the test, as for any
  change. Add a row to the rule the code cites; a new rule is for new behaviour.
- **Equivalent.** No input can tell the mutant apart from the code, e.g.
  `split(sep, 1)[0]` made `split(sep, 2)[0]`. Note it, and move on.
- **Dead code.** A guard nothing can reach. The finding is the guard.

The `mutation-analyst` agent turns a `report` into rule ids and killing
assertions.

## A module at a time

A change to a domain module changes its mutants, and `run` refuses a module
that changed since `init`: a mutant is the nth occurrence of an operator in
the source `init` read. So after a change, run `init` again, then try only
that module's mutants:

```bash
python dev/mutation/mutate.py init
python dev/mutation/mutate.py run --only web.py
```

A small module is minutes. `scoring.py` has some 850 mutants, a fifth of the
total, and is the slowest. `init` always takes its 10 minutes or so, because the
coverage map is the whole suite's. `--cap 0` costs most where it matters: on
2026-09-30, the 125 mutants on the capped survivors' lines took 17 minutes in
full.

## The first run

The first run was on 2026-09-30:

- 4,055 mutants, three hours on 14 workers;
- about 15% survived before triage;
- forty example rows came out of it, over thirteen specs.

`docs/history/slices.md` has what it found, and why most survivors were not
worth a row.

If a run is stopped, a `pytest` it started can outlive it. Find those by the
`--basetemp=…dossier-mutation…` in their command lines.
