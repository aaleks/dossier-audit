# 17 · Procedures as context

**You will build:** an incident audit that checks each incident against the
procedures that apply to it. The procedures are read, shown to the step that
needs them, and cited, but they are never audited themselves.

**You will learn:** what `reference:` means and what it does not, what a
`{{reference}}` placeholder holds in a call about one document, which
documents a field may cite and why that is decided per call, what an edited
procedure costs and which steps it costs, how a replay shows a past run the
procedures it read, and why reading `reference` with none declared is refused.

**Uses the stub model.** Offline, seconds, zero cost.

---

## Background, in one paragraph

An incident says what happened. Whether it was handled in time is not in the
incident. It is in the escalation procedure, which says how fast a major
incident goes to the incident commander. `pipeline.yaml` has always had a key
for this: `reference:`, whose comment in spec 003 reads *"context, not
audited"*. Until R3.17 and R3.18 it did not work. The run audited the
procedures as though they were incidents, and `{{reference}}` held the
incident a second time. This exercise is the key working as its comment says.

---

## The documents

```
playground/corpus/incidents/
  PLAY-1001.md       a major incident, with a recorded loss of CHF 18'400
  PLAY-1002.md       a minor incident, with no loss
resources/procedures/
  PLAY-6001.md       escalation: 30 minutes for a major incident, 4 hours for a minor one
  PLAY-6002.md       customer communication
resources/later/
  PLAY-6001.md       the escalation procedure, tightened to 15 minutes (task 3)
```

Terminal 1, the stub:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/17-procedures-as-context/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Its log records, for every call, the keys of the documents its prompt wrapped.
That list is how you will tell what each call was shown.

## Task 1 — two folders, read two ways

Make a workspace under `playground/work/17/`. Copy the two incidents to
`inbox/incidents/`, the two procedures to `inbox/procedures/`, and exercise
02's `resources/env.sample` to `.env`. Write `sources.yaml` with a `folder`
source for each. Then write `pipelines/incident-verify/pipeline.yaml`
naming `incidents` under `sources:` and `procedures` under `reference:`. Sync.

**Checkpoint.**

```
incidents  0 known · 0 changed · 2 new -> 2 fetched
procedures  0 known · 0 changed · 2 new -> 2 fetched
```

Both are synced. A pipeline cannot check an incident against a procedure it
has not fetched (R2.12 row 2).

## Task 2 — extract, then verify against the procedures

Declare two fields: `loss_amount` (`amount`, `CHF`) and `escalation_limit`
(`reference`). Write two steps:

- `extract`, reading `documents`;
- `verify`, reading `[documents, extract, reference]`, whose prompt puts
  `{{reference}}` inside a `<procedures>` tag.

Both are `per_file`. Run.

**Checkpoint.**

```
  extract: 2 document(s) · 0 from cache · 0 failed
  verify: 2 document(s) · 0 from cache · 0 failed
```

Four calls in the log. `extract`'s each hold one incident. `verify`'s hold
four keys each:

```
['PLAY-1001.md', 'PLAY-1001.md', 'PLAY-6001.md', 'PLAY-6002.md']
```

- Why two documents and not four? What would `extract/PLAY-6001.md.json` have
  held, and who would have scored it? (R3.17.)
- `PLAY-1001.md` appears twice in `verify`'s list. Which two inputs put it
  there? (R3.13.)
- The call about `PLAY-1002.md` is shown both procedures too, including the one
  about customers. Why every procedure, and not the ones that apply? (R3.18.)
- Open `runs/<id>/manifest.json` and find `reference`. Why is it a list of its
  own, beside `documents`? (R4.16.)

Then open `verify/PLAY-1001.md.json`. Its `escalation_limit` is `30 minutes`,
cited from `PLAY-6001.md`, and there is no finding. `extract` answered it
`null`: it was never shown a procedure.

## Task 3 — the procedure is tightened

Copy `resources/later/PLAY-6001.md` over the one in `inbox/procedures/`, sync,
and plan.

**Checkpoint.**

```
  extract: cached
! verify: documents changed
      moved: [PLAY-6001.md changed]
```

Run it. Two calls, both `verify`'s. `extract: 2 document(s) · 2 from cache`.
`verify/PLAY-1001.md.json` now says `15 minutes`.

- Why did every `verify` call run again, when only one incident is major?
  (R5.15.)
- Why is `extract` cached, though it runs over the same incidents? (R4.17.)
- Say what the plan would have printed if a procedure had been deleted rather
  than edited, and why that is a change at all when a deleted incident is not
  (R4.17 row 3).

## Task 4 — replay the first run

```bash
dossier run --replay runs/<task 2's run id>
```

**Checkpoint.** `4 artifact(s) reproduced · no model calls`. The workspace now
holds the 15-minute procedure, and the replay reproduced the 30-minute answer
without asking anything. Where did it find the procedure's old text?

## Task 5 — quotes from documents the call never read

Restart the stub with `resources/replies-wrong-document.json` given first, then
`replies.json`. That file makes two mistakes in `extract`:

- `PLAY-1002.md`'s loss is quoted from `PLAY-1001.md`, which does say it.
- `PLAY-1001.md`'s escalation limit is quoted from `PLAY-6001.md`, which also
  says it.

Delete `.dossier/cache/stage/` and run.

**Checkpoint.**

```
  extract: 2 document(s) · 0 from cache · 0 failed · 2 finding(s)
    PLAY-1001.md  escalation_limit: cites 'PLAY-6001.md', which was not an input to this stage. ...
    PLAY-1002.md  loss_amount: cites 'PLAY-1001.md', which was not an input to this stage. ...
```

Both quotes are true. Both are refused.

- Why refuse a quote that a reviewer could find, word for word? (R6.3, R6.23.)
- `verify` quoted the same procedure in task 2 without a finding. What is
  different about its call?
- Before R6.23, the first mistake was graded **grounded**, and only because of
  how the run handed documents to the check. Which document did the
  `PLAY-1002.md` call have to be shown for that to be right?

## Task 6 — context that is not there

Delete the `reference:` line from `pipeline.yaml`, and plan.

**Checkpoint.** Refused before anything runs, with exit 2:

```
pipeline.yaml: step 'verify' reads 'reference', but the pipeline declares no
`reference:` sources for it to hold. ...
```

What would `verify`'s `<procedures>` tag have held, and what would its prompt
still have told the model? (R3.18 row 4.) Put the line back.

---

## Done when

- an incident is checked against a procedure, and the answer cites the
  procedure;
- you can say what `{{reference}}` holds in any mode, and why the same for
  every call;
- you can explain, per rule, what `reference:` does to what is audited (R3.17),
  to what a call is shown (R3.18), to the manifest and a replay (R4.16), to a
  plan (R4.17), to keys (R5.15), and to what a field may cite (R6.23).

A judged field of a step that reads `reference` is put to the judge with the
procedures as well as its document (R7.34). Exercise 07 shows calibration, and
the same steps work here with a free-text field on `verify`.

**Back to:** [the playground index](../README.md).
