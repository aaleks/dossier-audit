# 09 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/09-cache-keys-determinism-and-replay/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl &

mkdir -p playground/work/09a/inbox/incidents
cp -r playground/09-cache-keys-determinism-and-replay/solution/workspace/. playground/work/09a/
cp playground/corpus/incidents/PLAY-100[1-4].md playground/work/09a/inbox/incidents/
cp playground/09-cache-keys-determinism-and-replay/resources/env.sample playground/work/09a/.env

cd playground/work/09a
D=../../../.venv/bin/dossier
$D sync incident-audit && $D run incident-audit
```

---

## Task 1 — the three namespaces

```
.dossier/cache/convert/<2>/<2>/<key>      snapshot hash + converter id + version + options
.dossier/cache/stage/<2>/<2>/<key>        prompt hash + declaration hash + generated schema
                                          hash + model id + input hashes
.dossier/cache/judge/<2>/<2>/<key>        candidate hash + document hash + judge model +
                                          rubric hash + judge prompt hash
```

**Why namespaces**, given that every key is a SHA-256 of its own inputs? Because a
namespace per kind of computation means a convert key and a stage key can never
collide *even if some future composition made them equal* — the comment in
`src/dossier/infrastructure/cache.py` says exactly that. It costs a directory and
buys immunity from a class of bug nobody would ever find.

Notice what is in a judge key and what is not: the candidate, the document, the
judge, the rubric and the wrapper are in it; the **run id is not**, though it is
in the record. Two runs that produced the same candidate over the same document
asked the same question, so the second one is free (R7.18).

## Task 2 — the six changes

What actually happened:

| # | change | `--plan` said | the run did | agree? |
|---|---|---|---|---|
| 1 | prompt edited | `! extract: prompt changed` | 4 calls | ✅ |
| 2 | declaration edited | `! extract: declaration changed` | 4 calls | ✅ |
| 3 | one note edited, synced | `extract: cached` | 1 call, 3 from cache | ❌ |
| 4 | model identifier changed | `extract: cached` | 4 calls | ❌ |
| 5 | endpoint URL changed | `extract: cached` | 0 calls, 4 from cache | ✅ |
| 6 | the stub's answer edited | `extract: cached` | 0 calls, 4 from cache | ✅ |

Rows 5 and 6 are the two that make this playground possible, and they are worth
saying out loud:

- **Where** a model is served is per machine and in no key (R9.2). Move the
  endpoint, and one identifier reached from two machines still shares one cache.
- The model's **answer** is not in the key; the question is. Editing the stub's
  reply changes nothing until the question changes.

### The two rows where `--plan` was wrong

```console
$ dossier run --plan incident-audit        # after changing model: to openai:gpt-4o-2024-08-06
incident-audit  4 document(s) · model openai:gpt-4o-2024-08-06
compared against 20260917T211133Z-1c63
  extract: cached
0 of 1 step(s) would run · nothing written

$ dossier run incident-audit
  extract: 4 document(s) · 0 from cache · 0 failed
```

The plan said nothing would run. The run made four model calls.

The same shape for a changed document: `--plan` reports `cached`, and the run
re-asks for the one document whose snapshot moved (`3 from cache`).

R4.12 is unambiguous about what that should be: "`--plan` reports a step as
re-running exactly when a run would miss its cache… `cached` means the next run
will serve that step from the cache, and anything else means it will ask the
model." The rule's own history says why it exists — before it, `build_plan`
resolved without the prompt and declaration hashes that `execute` keys on, so a
prompt edit printed `cached` and then missed, "one answer arrived at two ways".

The prompt and declaration halves of that were fixed. The model identifier and the
document hashes were not: `diff` in `src/dossier/domain/plan.py` compares a step's
inputs, prompt hash and declaration hash against the previous manifest, while the
stage key in `src/dossier/application/run.py` also covers `model.model_id` and the
hash of each input document's text.

**What a person relying on `--plan` would have concluded:** that switching models
on a large corpus costs nothing, and that re-running after a sync is free. Both
are exactly the questions `--plan` exists to answer, and both would be wrong in
the expensive direction.

What this repository would do with that is not "patch `diff`". It is to report
it — the rule and the code disagree, and which of them is right is a decision for
whoever owns spec 004. Two candidate shapes, both worth arguing:

- **the plan is keyed the way the run is**: include the model identifier and the
  documents' hashes in the comparison, and report `model changed` and
  `documents changed` as statuses alongside `prompt changed`;
- **the plan is about the pipeline, not the corpus**: keep `diff` as it is and
  reword R4.12 so `cached` is a claim about the *step's configuration*, with the
  per-document arithmetic reported separately.

The first keeps the promise; the second admits it was never quite the promise
being made. Either is a spec change first and a code change second.

## Task 3 — the cache is not the truth

```console
$ find .dossier/cache/stage -type f ! -name '*.meta.json' | sort | xargs cat | sha256sum
dfcf50041737fc4c898b39596c84654a1b2c5ca5124b954687687056fc4ce684  -

$ rm -rf .dossier/cache && dossier run incident-audit
  extract: 4 document(s) · 0 from cache · 0 failed

$ find .dossier/cache/stage -type f ! -name '*.meta.json' | sort | xargs cat | sha256sum
dfcf50041737fc4c898b39596c84654a1b2c5ca5124b954687687056fc4ce684  -
```

Byte for byte. Deleting the cache changed the *cost* — four more model calls in
the log — and nothing else (R5.9). That property is what lets you delete a cache
without a meeting.

A damaged entry:

```console
$ # one artifact truncated to `{"document": "trunc`
$ dossier run incident-audit
  extract: 4 document(s) · 3 from cache · 0 failed

$ # one .meta.json removed instead
$ dossier run incident-audit
  extract: 4 document(s) · 3 from cache · 0 failed
```

Both are misses, not authority. An artifact whose bytes do not parse is redone; an
artifact with no provenance record beside it **is not a cache entry at all**
(R0.3), so it is redone too. The alternative — trusting either — would make one
corrupt file permanently fatal to a workspace whose inputs are all still present.

The write order is the other half of that. `put` writes the artifact first and the
record second, through a temporary name and a rename: killed between the two, the
entry reads back as a miss and is recomputed. The other order would leave a record
describing an artifact that is not there, which looks complete.

## Task 4 — two machines, one key

```console
$ diff <(cd work/09a && find .dossier/cache/stage -type f ! -name '*.meta.json' -printf '%f\n' | sort) \
       <(cd work/09/deeper/nested && find .dossier/cache/stage -type f ! -name '*.meta.json' -printf '%f\n' | sort)
$ echo $?
0
```

Identical keys:

```
a4eff980d6ddd7d3d2862d7ef47acb705bfc2ace8e940a51cb8c46f6790bbda8
b6a49caeb2df0103c9fc97ffee4390066f788f5ae7261f3e8f13dc1f503ec566
c7c0845c5b3c13f2c0fc1cc1815925b44acfc712a204afd14ab5f4a77fd506ff
df36fd6c50784b8b4b84a463340a78af8eeb6c226cfdd834ae965c6a2a49cc3d
```

Different absolute paths, different directory depth, same keys. That is the
observable form of R0.4 and R5.6 — and it is only true because a long list of
small decisions went the other way than they usually do:

- the folder connector sorts by the **key string**, not by `Path`: `PurePath`
  comparison is case-insensitive on Windows and case-sensitive on Linux, so
  `sorted(paths)` would order two files differently on two machines;
- the connector builds keys with forward slashes regardless of platform;
- media types come from dossier's own table, never from the host;
- the converter registry sorts by the pair each converter claims, because
  `entry_points()` returns whatever order the environment produces;
- the generated schema is hashed over canonical JSON — sorted keys, fixed
  separators — so the same schema is the same bytes however the dict was built;
- the domain layer takes its clock as an argument and imports nothing that could
  read one.

Grep `src/dossier/` for `sorted(` and read the comment above each. Almost every
one names the machine-dependent thing it is defending against. That is the habit
to steal: when you sort for determinism, say so where you sort, because the next
person will otherwise remove it as noise.

## Task 5 — what a replay refuses

```console
$ # one stage artifact deleted
$ dossier run --replay runs/20260917T211133Z-1c63/
step 'extract' has no cached artifact for 'PLAY-1004.md' at a4eff980d6dd…; this run cannot
be reproduced from this workspace, and nothing has been substituted for it.
exit 2
```

It fails, by name, and substitutes nothing. "A replay may fail; it may never
substitute other content" (R4.7). Re-asking the model here would be the most
seductive possible bug: the command would succeed, the output would look like the
original run, and it would be a different run wearing its id.

```console
$ # pipeline.yaml edited: model: openai:gpt-4o-2024-08-06
$ dossier run --replay runs/20260917T212614Z-8cd8/
replayed 20260917T212614Z-8cd8 · incident-audit
  extract: 4 artifact(s) from cache
4 artifact(s) reproduced · no model calls
exit 0
```

Unchanged, and it never opened `pipeline.yaml` — not to check that it agrees, not
to warn that it has changed. A replay that consulted today's configuration would
be reproducing today's configuration rather than the run.

**No converter, no endpoint, no problem.** A replay reads conversions back *by
their keys* rather than re-converting, so it needs no converter installed at all —
the same shape as needing no model client. That is not a convenience: raising a
converter version is how R5.4 invalidates conversions, so re-converting during a
replay would produce text the original run never saw.

---

## Where to go from here

You have now touched every command and most of the rules. Three suggestions:

1. **Read a spec end to end** — `specs/005-caching-and-keys.md` is the one this
   exercise is about, and it reads differently once you have seen the keys on
   disk. Then `specs/README.md` for how the rules are written and checked.

2. **Run the repository's own checks**, which are the mechanical half of the
   working agreement:

   ```bash
   pytest                     # offline, seconds, zero cost
   pytest tests/architecture  # the boundaries and the spec/test cross-references
   ```

3. **Apply it to your own project.** The transferable core of `dossier` is five
   decisions, none of which need this codebase:

   - freeze the evidence and address it by content;
   - key the work by the question, and make every input to that key content-derived;
   - make a claim checkable without a model wherever you possibly can;
   - measure any judge you intend to quote, against human verdicts, on the
     question it will actually be asked;
   - compute each figure once, and let every other surface read it rather than
     derive it.

   The rest — the ledger schema, the CLI shape, the YAML — is detail you would
   redesign for your own corpus anyway.
