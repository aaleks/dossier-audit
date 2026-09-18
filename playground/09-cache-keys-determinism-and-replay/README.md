# 09 · Cache keys, determinism and replay

**You will build:** nothing new. You will take a workspace apart and find out
exactly what makes `dossier` ask a model again — and what does not.

**You will learn:** what each cache namespace holds, which inputs are in a stage
key, why two machines compute the same key, what a replay needs and what it
refuses, and where `--plan` promises more than it can keep.

**Uses the stub model.**

---

## Background, in one paragraph

A cache key is a claim: *these inputs determine this artifact*. Every key in
`dossier` is composed from content — hashes of the prompt template, the field
declaration, the converted inputs, the pinned model identifier — and from nothing
else. No paths, no timestamps, no machine names, no `hash()`, no unsorted set
iteration. That is what lets two people on two machines share one cache, and it is
what makes "reproducible" a testable claim rather than an aspiration (R0.4, R5.6).

---

## Setup

A fresh workspace from exercise 02's solution, synced and run once, with the stub
running.

## Task 1 — the three namespaces

Look under `.dossier/cache/`.

**Checkpoint.** Three directories: `convert`, `stage` and `judge` (the last only
once you have run an eval with a judged field). Each artifact has a `.meta.json`
beside it. Open one record from each namespace and compare what goes into each
kind of key.

Then answer: why namespaces at all, when every key is a SHA-256 of its own inputs
and collisions are not a practical concern?

## Task 2 — the six changes

For each of these, predict first, then run `dossier run --plan` **and** `dossier
run`, and record what actually happened:

| # | change |
|---|---|
| 1 | add a sentence to `prompts/01_extract.md` |
| 2 | add a value to the `severity` enum in `schemas/incident.yaml` |
| 3 | append a line to one incident note, then `dossier sync` |
| 4 | change `model:` in `pipeline.yaml` to another pinned identifier |
| 5 | change `DOSSIER_OPENAI_URL` in `.env` to a different port (move the stub too) |
| 6 | edit an answer in the stub's `replies.json` |

**Checkpoint.** Three columns for each row: what `--plan` said, what the run did,
and whether they agreed. All six should agree — R4.12 says "`--plan` reports a
step as re-running exactly when a run would miss its cache… `cached` means the
next run will serve that step from the cache".

Two of them did not, until this playground was written. Before you read the
solution, work out **which two** you would expect to be the hard ones: which of
these changes is something a person edits in `pipelines/`, and which is something
about the world the pipeline runs in? That distinction is where the bug lived, and
the solution tells the story of the fix — a spec commit, then a code commit.

While you are here, predict the status word for row 3 as well. The plan names the
documents it would re-ask for, and there is a reason it names them rather than
counting them.

## Task 3 — the cache is not the truth

```bash
find .dossier/cache/stage -type f ! -name '*.meta.json' | sort | xargs cat | sha256sum
rm -rf .dossier/cache
dossier run incident-audit
find .dossier/cache/stage -type f ! -name '*.meta.json' | sort | xargs cat | sha256sum
```

**Checkpoint.** The same digest. Deleting the whole cache changes no output — it
only changes what it costs (R5.9). Then check what it did cost, in the stub's call
log.

Now damage a single entry: truncate one artifact, or delete one `.meta.json`, and
run again.

**Checkpoint.** A damaged entry is a miss, not authority. An artifact without a
provenance record is not a cache entry at all (R0.3, R5.8), so the work is redone
and the entry rewritten — rather than one corrupt file being permanently fatal to
a workspace whose inputs are all still present.

## Task 4 — two machines, one key

Build a second workspace at a *different path and depth* — `work/09/deeper/nested/` —
from the same solution files and the same corpus. Sync and run it.

```bash
diff <(cd work/09a && find .dossier/cache/stage -type f ! -name '*.meta.json' -printf '%f\n' | sort) \
     <(cd work/09/deeper/nested && find .dossier/cache/stage -type f ! -name '*.meta.json' -printf '%f\n' | sort)
```

**Checkpoint.** No difference. Same keys, different absolute paths, different
directory depth. Then go looking for what would have broken it: grep `src/dossier/`
for `sorted(` and ask, at each one, what would vary without it.

## Task 5 — what a replay refuses

Replay your most recent run, then:

1. Replay it again after deleting one stage artifact from the cache.
2. Replay it after editing `pipeline.yaml` — change the model, add a step.

**Checkpoint.** The first fails by name and substitutes nothing. The second
succeeds, unchanged, and never reads `pipeline.yaml` at all. Both are R4.7: a
replay may fail, and it may never reproduce something other than the run it names.

Then: what would it take to replay a run on a machine that has no converter
installed and no model endpoint configured? Try it — uninstall the PDF converter
from exercise 03 if you still have it, or unset the endpoint — and reason about
why the answer is what it is.

---

## Done when

- a table of six changes with predictions and observations, all six agreeing, and
  an account of why two of them once did not;
- a cache you deleted and rebuilt byte for byte;
- identical keys in two workspaces at different paths;
- a replay that failed honestly and one that ignored a configuration change.

**This is the last exercise.** What to do next is in the solution.
