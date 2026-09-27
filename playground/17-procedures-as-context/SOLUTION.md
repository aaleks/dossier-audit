# 17 · Solution

Every command below was run against this repository, in order and in one pass,
on 2026-09-27, against the stub. The output shown is the output it produced. The
workspace's absolute path is cut from the `run` lines, and the run ids and
snapshot addresses are that pass's. Yours will differ.

## Run the prepared answer

Terminal 1:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/17-procedures-as-context/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Terminal 2:

```bash
E=playground/17-procedures-as-context
mkdir -p playground/work/17/inbox/incidents playground/work/17/inbox/procedures
cp -r $E/solution/workspace/. playground/work/17/
cp playground/corpus/incidents/PLAY-100[12].md playground/work/17/inbox/incidents/
cp $E/resources/procedures/*.md playground/work/17/inbox/procedures/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/17/.env

cd playground/work/17
D=../../../.venv/bin/dossier
$D sync incident-verify && $D run incident-verify
```

To see what each call was shown, one line per call:

```bash
python -c "import json; [print(json.loads(l)['documents']) for l in open('/tmp/dossier-calls.jsonl')]"
```

---

## Task 1 — two folders, read two ways

```yaml
# pipeline.yaml
sources: [incidents]
reference: [procedures]
```

```console
$ dossier sync incident-verify
incidents  0 known · 0 changed · 2 new -> 2 fetched
procedures  0 known · 0 changed · 2 new -> 2 fetched
ledger updated · 4 new snapshots · 0 tombstoned
```

`dossier sync <pipeline>` syncs `sources:` and `reference:` alike, because a
reference document is an input and must be held before a run can read it
(R2.12 row 2).

## Task 2 — extract, then verify against the procedures

```yaml
fields:
  loss_amount:      {kind: amount, currency: CHF}
  escalation_limit: {kind: reference}
```

```yaml
steps:
  - id: extract
    prompt: prompts/01_extract.md
    input: documents
    mode: per_file
    output: schemas/incident.yaml

  - id: verify
    prompt: prompts/02_verify.md
    input: [documents, extract, reference]
    mode: per_file
    output: schemas/incident.yaml
```

```console
$ dossier run incident-verify
run 20260927T152538Z-291a · runs/20260927T152538Z-291a/manifest.json
  extract: 2 document(s) · 0 from cache · 0 failed · tokens not reported
  verify: 2 document(s) · 0 from cache · 0 failed · tokens not reported
```

The log, each call's first words and the keys it was shown:

```
Extract the requested fields ['PLAY-1001.md']
Extract the requested fields ['PLAY-1002.md']
Check the extraction below a ['PLAY-1001.md', 'PLAY-1001.md', 'PLAY-6001.md', 'PLAY-6002.md']
Check the extraction below a ['PLAY-1002.md', 'PLAY-1002.md', 'PLAY-6001.md', 'PLAY-6002.md']
```

**Two documents, not four.** The procedures are context. No step is asked
about one, and nothing is filed under its key (R3.17). `extract/` and `verify/`
each hold `PLAY-1001.md.json` and `PLAY-1002.md.json`, and nothing else.
Asked about `PLAY-6001.md`, `extract` would have been asked for a procedure's
loss amount, a question nobody asked. It would have been paid for, and no gold
answer would ever score it. Before R3.17 that is exactly what a run did.

**`PLAY-1001.md` twice.** Once from `documents`, the incident, and once from
`extract`, whose answer about it is wrapped under the same key. Every input
names the document it came from (R3.13).

**Both procedures in every call.** `{{reference}}` holds every reference
document, each under its own key, in key order, whatever the mode (R3.18).
The call about `PLAY-1002.md` is shown byte for byte what the call about
`PLAY-1001.md` is. Choosing which procedures apply is a judgement, and the
step exists to make it. A run that pre-chose would be deciding the answer before
asking. The cost is plain: every procedure, in every call.

**The manifest:**

```
documents ['PLAY-1001.md', 'PLAY-1002.md']
reference ['PLAY-6001.md', 'PLAY-6002.md']
```

A list of its own, because a key cannot say it was context. `PLAY-6001.md`
looks like any other file of a folder. A replay has to know which documents
to show every call, and this list is how it knows (R4.16).

`verify/PLAY-1001.md.json`, value, source and span:

```
loss_amount       18400.0     <- PLAY-1001.md | recorded loss of CHF 18'400
escalation_limit  30 minutes  <- PLAY-6001.md | within 30 minutes
```

`extract/PLAY-1001.md.json`:

```
loss_amount       18400.0     <- PLAY-1001.md | recorded loss of CHF 18'400
escalation_limit  None        |  not stated in document
```

No finding on either: `verify` was shown `PLAY-6001.md`, so it may cite it
(R6.3 row 3, R6.23).

## Task 3 — the procedure is tightened

```console
$ dossier sync incident-verify
incidents  2 known · 0 changed · 0 new -> 2 fetched
procedures  2 known · 1 changed · 0 new -> 2 fetched
      PLAY-6001.md  88f46e6b30b085db4922029366a73681af2f54c2ccb98c9d38facac701758d25 -> d647b1fa908c954bc3210049b601420eb9a887b656e491a6b67b7828508f69c5
ledger updated · 1 new snapshots · 0 tombstoned

$ dossier run incident-verify --plan
incident-verify  2 document(s) · model openai:gpt-5.4-mini
compared against 20260927T152538Z-291a
  extract: cached
! verify: documents changed
      moved: [PLAY-6001.md changed]
1 of 2 step(s) would run · nothing written

$ dossier run incident-verify
warning: the source has moved since run 20260927T152538Z-291a: PLAY-6001.md re-snapshotted (reference)
run 20260927T152541Z-e3d3 · runs/20260927T152541Z-e3d3/manifest.json
  extract: 2 document(s) · 2 from cache · 0 failed
  verify: 2 document(s) · 0 from cache · 0 failed · tokens not reported
```

**The warning** names the procedure, marked `(reference)`, before any step
runs. A new run reads what is held now, and this line is the one moment it
says that two runs are no longer over the same evidence (R4.9 row 5). No
incident moved, so a warning that compared only audited documents would have
said nothing. It did, until R4.9 row 5.

Two new calls, both `verify`'s:

```
Check the extraction below a ['PLAY-1001.md', 'PLAY-1001.md', 'PLAY-6001.md', 'PLAY-6002.md']
Check the extraction below a ['PLAY-1002.md', 'PLAY-1002.md', 'PLAY-6001.md', 'PLAY-6002.md']
```

and `verify/PLAY-1001.md.json` now reads `15 minutes <- PLAY-6001.md | within 15
minutes`.

**Every `verify` call ran again**, including `PLAY-1002.md`'s, whose minor-incident
limit did not move. Each call was shown the whole procedure, so each key holds
its text (R5.15). The key cannot know which sentence an answer leaned on. It
holds what the call was shown, and nothing else (R0.5).

**`extract` is cached** because it never read a procedure, so no key of its
holds one (R5.15 row 2). The plan says so before anything runs (R4.17). Before
R4.17, a plan compared a run's procedures as if they were audited documents, and
reported every step as re-running.

**A deleted procedure.** Run at the end of this pass, with `PLAY-6002.md` moved
out of `inbox/procedures/` and synced (the sync reports it `tombstoned`):

```console
$ dossier run incident-verify --plan
incident-verify  2 document(s) · model openai:gpt-5.4-mini
compared against 20260927T152548Z-866a
  extract: cached
! verify: documents changed
      moved: [PLAY-6002.md gone]
1 of 2 step(s) would run · nothing written

$ dossier run incident-verify
warning: the source has moved since run 20260927T152548Z-866a: PLAY-6002.md gone (reference)
```

An incident that leaves the source takes only its own keys with it, so a plan
does not report it. A procedure was shown to every `verify` call, so every one
of those keys moves when it goes (R4.17 row 3). The run's warning names it the
same way (R4.9 row 5).

## Task 4 — replay the first run

```console
$ dossier run --replay runs/20260927T152538Z-291a
replayed 20260927T152538Z-291a · incident-verify
  extract: 2 artifact(s) from cache
  verify: 2 artifact(s) from cache
4 artifact(s) reproduced · no model calls · written to runs/20260927T152538Z-291a/replays/20260927T152542Z-88fa/
```

**The old text** came from the manifest's `reference` list, which pins
`PLAY-6001.md` at the snapshot the run read, `88f46e6b…`. Snapshots are never
overwritten (R0.2), so the 30-minute text is still held, and the replay reads
it back by that address. The ledger now points at `d647b1fa…`, and the replay
never asks the ledger (R4.16, R4.7).

## Task 5 — quotes from documents the call never read

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/17-procedures-as-context/resources/replies-wrong-document.json \
  --replies playground/17-procedures-as-context/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

```console
$ rm -rf .dossier/cache/stage/
$ dossier run incident-verify
run 20260927T152548Z-866a · runs/20260927T152548Z-866a/manifest.json
  extract: 2 document(s) · 0 from cache · 0 failed · 2 finding(s) · tokens not reported
    PLAY-1001.md  escalation_limit: cites 'PLAY-6001.md', which was not an input to this stage. Inputs were ['PLAY-1001.md'] (R6.3).
    PLAY-1002.md  loss_amount: cites 'PLAY-1001.md', which was not an input to this stage. Inputs were ['PLAY-1002.md'] (R6.3).
  verify: 2 document(s) · 0 from cache · 0 failed · tokens not reported
```

**Why refuse a true quote.** The call about `PLAY-1002.md` was shown one
incident, and it answered with another incident's loss. A reviewer who followed
the citation would find CHF 18'400, word for word, in `PLAY-1001.md` and sign off.
Nothing about the citation says the call never read it. A citation that leads
nowhere fails the first time anyone follows it. This one never fails, which
makes it worse than none (R6.3). A field cites a document its call was shown
(R6.23).

**What is different about `verify`'s call** is its inputs. `verify` reads
`reference`, so it was shown `PLAY-6001.md` and may cite it. `extract` reads
`documents` only, so for `extract` the same quote cites a document it was never
shown.

**Before R6.23**, the run handed every `per_file` call's check the whole
corpus, so the `PLAY-1002.md` answer quoting `PLAY-1001.md` was graded
grounded. That grade would only have been right if the call had been shown
`PLAY-1001.md`, and it was not.

## Task 6 — context that is not there

```console
$ dossier run incident-verify --plan
pipeline.yaml: step 'verify' reads 'reference', but the pipeline declares no `reference:` sources for it to hold. Name them under `reference:`, or remove the input.
exit 2
```

`<procedures>` would have held nothing, and the prompt would still have told
the model to fill in what the procedures say applies. The model, asked for a
procedure it was not given, would have answered from what it remembers of
procedures in general. So the pipeline is refused when it loads, as a step
reading a kind no source makes is (R4.13, R3.18 row 4).
