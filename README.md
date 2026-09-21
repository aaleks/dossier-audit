# dossier-audit

Document collection and audit pipeline. Syncs documents from configured sources,
freezes them as immutable snapshots, converts them — to text, and to one picture
per page — runs a sequence of prompt stages over them, and scores the results
against human-verified answers.

Package and CLI: `dossier`.

**Status: implemented.** 165 rules across 12 specs, all of them `MET` or
superseded in place, no open acceptance test. The specs came first and the code
implements them — see "How this is built" below.

```
specs: 165 rules across 12 specs | 156 MET, 0 IN PROGRESS, 0 NOT MET, 9 SUPERSEDED
       162 deterministic, 3 evaluated
```

## Layout

| Path | What |
|---|---|
| `specs/` | The source of truth. Start at `specs/000-overview.md`, then `specs/README.md` for the index. |
| `CLAUDE.md` | The working agreement for this repository |
| `docs/architecture.md` | The two boundaries and the layer contracts |
| `docs/dossier-design-deck.pdf` | Background: the proposal this came from |
| `src/dossier/` | The package: `domain/`, `application/`, `infrastructure/`, `config/`, `cli/` |
| `tests/` | `architecture/`, `unit/`, `acceptance/`, `integration/`, `evals/` |
| `playground/` | Ten hands-on exercises. Offline, seconds, zero cost. Not part of `dossier`. |
| `KICKOFF.md` | Prompt for the first implementation session |
| `.claude/` | The spec-driven toolchain: skills, agents, rules, hooks |

## Installing

```bash
pip install dossier            # markdown-text, text-plain, png-pages
pip install dossier[pdf]       # and pdf-markdown, pdf-images, jpeg-pages
pip install dossier[tracking]  # and MLflow runs, traces and metrics
```

`jpeg-pages` is under the `pdf` extra despite its name: it decodes through
Pillow, which the PDF converters need anyway and nothing else in `dossier` does.
`png-pages` needs neither, because a PNG page image is the file it was given.

Converters, connectors and model providers are all resolved from entry points,
never hard-coded: what a run can read depends on what is installed, and the
manifest records which converters it actually used.

## Commands

```
dossier sync <pipeline>              # fetch only what changed
dossier sync <pipeline> --full       # ask every source for an unwindowed listing
dossier convert <pipeline>           # each document to the kinds its source declares
dossier run <pipeline> --plan        # what would run, and why
dossier run <pipeline>               # execute; writes runs/<id>/ as it goes
dossier run --replay runs/<id>/      # reproduce a past run exactly, with no model call
dossier calibrate <pipeline> --gold … # measure each judge against its human-scored sample
dossier eval <pipeline> --gold …     # score against verified answers
dossier eval <pipeline> --compare a b
dossier dataset publish <pipeline> --gold …  # the gold set as an MLflow evaluation dataset
```

## What it reads

A source declares the kinds it converts to, and a step names the kind it reads:

```yaml
# sources.yaml
  - id: postmortems
    type: folder
    path: inbox/postmortems/
    convert: [markdown, page_images]

# pipeline.yaml
  - id: extract
    input: documents@page_images
    mode: per_part
    output: schemas/incident.yaml
```

`markdown` is what a bare `documents` means, so every pipeline written before
kinds could be named still reads the same. `page_images` is one picture per page,
delivered as a single container of parts (R8.11); a `per_part` step is run once
per page, keyed and retried and cached per page (R3.12).

That matters because not every document has a sentence in it. A figure drawn on a
chart is in no text, so a field citing it is **`described`** — neither a pass nor
a failure, because the evidence is on a page the model looked at and a string
search is the wrong instrument for it (R6.15). `dossier eval` puts such a field
to a judge with the document's pages in place of a transcript, and that judge is
calibrated and gated on its own threshold, separately from the one that reads
text (R7.20–R7.24).

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

Rule ids never move. A rule that stops being true is **superseded in place** and
names its replacement — nine of the 165 are — because test filenames and other
rules cite those ids, and rewriting the text under one would leave every test
citing it claiming to prove something nobody agreed to.

## Running the tests

```bash
uv sync --all-extras    # extras and the dev group; `pip install -e ".[pdf,tracking]"`
                        # plus pytest and ruff does the same by hand

pytest                  # the default suite: offline, seconds, zero cost
pytest -m outer_loop    # the open slice, when there is one. Red until it lands
pytest -m live          # the evaluated rules. Real model calls, run deliberately
```

The default suite blocks network access outright — an autouse fixture refuses
socket creation for any test not marked `live`. That is not test hygiene, it is
R0.10: exactly three packages may reach the network, and everything right of that
line is a pure function of content hashes, which is what makes a run from six
months ago reproducible.

`pytest tests/architecture` is the mechanical half of the working agreement. It
walks every module with `ast` to check the hash boundary and the layer contracts,
and it checks that every spec rule and every test file still refer to each other.

## Learning it by running it

`playground/` has ten exercises that build a workspace, sync a folder, define a
pipeline, ground an answer, calibrate a judge, read the run back in MLflow, and
audit a chart. They run offline against a stub model server in
`playground/toolkit/`, so the code path is the real one and the answers are yours
to control. Start at `playground/README.md`.
