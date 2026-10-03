# 25 · A client's name, masked before it leaves

**You will build:** an audit of four incident notes, in English, German,
French and Italian, that name a client: who called, from which phone, about
which account. You will run it once as it is, and read exactly what the model
was sent. Then you will declare masking and read it again.

**You will learn:**
- how a pipeline declares masking, and that it is off unless declared;
- what a masked document looks like to a model, and why each value is numbered;
- where the masked view is kept, and what its record says and never says;
- which configurations are refused rather than sent unmasked;
- why a file name is checked as well as a file;
- what the score threshold decides;
- what an allow-list is for;
- what masking promises, and what it only measures.

**Needs the masking extras.** `masking` is Presidio and spaCy. `masking-models`
is spaCy's four `lg` models, about 2 GB, installed once. After that it runs
offline. The model is the stub, started with a launcher that writes each
prompt into its call log, so you can read what reached the model.

---

## Background, in one paragraph

A pipeline sends its documents to a model, and incidents name clients. A root
cause is the same whoever it happened to, so the model has no use for the name.
Spec 021 lets a pipeline mask client identifying data on this machine, before
anything is sent. Presidio finds candidate values with spaCy's named-entity
models and pattern recognisers, and `dossier` decides what is masked and how
it reads. Snapshots and conversions stay as they were fetched: masking is a
view a pipeline asks for, not a change to the evidence.

---

## Setup

```bash
uv sync --extra masking --extra masking-models
```

Terminal 1, the stub. It is the toolkit's, with the full prompt in its log:

```bash
.venv/bin/python playground/25-a-client-masked-before-it-leaves/resources/stub_model_capturing.py \
  --replies playground/25-a-client-masked-before-it-leaves/resources/replies.json \
  --port 8099 --log /tmp/dossier25-calls.jsonl
```

Terminal 2:

```bash
E=playground/25-a-client-masked-before-it-leaves
mkdir -p playground/work/25/inbox/tickets
cp -r $E/solution/workspace/. playground/work/25/
cp $E/resources/tickets/*.md playground/work/25/inbox/tickets/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/25/.env
cd playground/work/25
```

The prepared `pipeline.yaml` already ends with `masking: masking/cid.yaml`.
That is where task 2 ends up. For task 1, delete that line.

The four notes are `PLAY-6001` to `PLAY-6004`, the canary corpus of
`specs/_fixtures.md`. Every value in them is fictional, and chosen so that you
can search for it.

---

## Task 1 — what the model was sent

Delete the last line of `pipelines/incident-audit/pipeline.yaml`, then sync and
run. Every line of `/tmp/dossier25-calls.jsonl` is one call, and `prompt` is
what it carried. Search the prompts for the client: `Erika Mustermann`, her
e-mail, her phone number, her IBAN `CH93 0076 2011 6238 5295 7`, her AHV number
and her client number `CIF 0042-118733`.

How many of the seven values does each call carry?

## Task 2 — declare masking

Put `masking: masking/cid.yaml` back, read `masking/cid.yaml`, and run again,
with the call log emptied first.

1. Which values does each prompt still carry? What stands where they were?
2. `Hans Muster` and `Erika Mustermann` are both people. How are they told
   apart, and what would the model lose if both were `[PERSON]`?
3. Look under `.dossier/cache/mask/` for a `.meta.json`. Which language was
   the German note read in? What does the record count, and what does it
   never write down?
4. Run again without changing anything. How many times is the masker asked?

## Task 3 — what is refused, not sent

Each of these is a mistake that would leave a value unmasked. Try each one,
put it back, and note the exit code and how many calls reached the stub.

1. Delete `score_threshold:` from `cid.yaml`.
2. Make the step read pictures: `input: documents@page_images` in
   `pipeline.yaml`, and `{{documents@page_images}}` in its prompt.

## Task 4 — a file named after the client

Copy `PLAY-6001.md` to `inbox/tickets/Erika-Mustermann-complaint.md`. Its
text is masked like any other. What about its name? Sync, run, and read what
`dossier` says and the exit code. Then search the call log for
`Erika-Mustermann`. Remove the file and sync again when you are done.

## Task 5 — what the threshold decides

Add `inbox/tickets/PLAY-6005.md`:

```markdown
# PLAY-6005 Rückruf erbeten

Die Kundin bittet um Rückruf unter +41 44 555 01 23, sobald die Zahlung freigegeben ist.
```

Sync and run, and find the phone number in that note's prompt. Then set
`score_threshold: 0.4` and run again. Why does the same number score
differently in `PLAY-6002`, where the word `Telefon` stands beside it? Put the
threshold back to 0.5.

## Task 6 — what the allow-list is for

`masking/allow.txt` names one word. Comment out the `allow:` line in
`cid.yaml`, run, and read what the German note's prompt says about the
`Kafka` consumer. Put the line back. Why is a word like that better kept than
masked?

## Task 7 — what was promised

Write two sentences: one on what masking guarantees, and one on what it does
not. Spec 021's "What masking promises, and what it does not" is the place to
check your answer. Then name two things this exercise did not show.

---

The solution, with the output each task produced, is in `SOLUTION.md`.
