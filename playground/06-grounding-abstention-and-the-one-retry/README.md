# 06 · Grounding, abstention and the one retry

**You will build:** four runs that go wrong in four different ways, and read what
each one costs.

**You will learn:** what makes a field grounded, why a right answer with a bad
citation is still wrong, what abstention has to carry, how many times a model gets
to correct itself, and what happens to a document that never produces a valid
answer.

**Uses the stub model and the gold set from exercise 05.**

---

## Background, in one paragraph

Grounding is a string search, and that is the point: the claim is that grounding
is checkable *without* a model, and the moment it needs a judgement it stops being
free and starts being another thing to calibrate. A field cites a document and a
span; the span is normalised for whitespace on both sides and then looked for in
the converted text of that document. Not found means `ungrounded`, whatever the
value says — and an ungrounded field is scored incorrect even when its value
matches gold (R6.4, R7.4).

---

## Setup

Start from a copy of your exercise 05 workspace (gold set included). Each task
layers a different override file in front of the base replies, so restart the
stub each time:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/06-grounding-abstention-and-the-one-retry/resources/<variant>.json \
  --replies playground/06-grounding-abstention-and-the-one-retry/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Between tasks, clear the stage cache so the run actually asks again:

```bash
rm -rf .dossier/cache/stage runs
```

Deleting the cache is always safe — it is an optimisation and never a source of
truth (R5.9), and exercise 09 proves that by checking the bytes that come back.

## Task 1 — a right answer with a wrong citation

Variant: `replies-ungrounded.json`. It answers `PLAY-1001`'s `loss_amount` as
`18400.0` — exactly what gold says — and cites the span `a recorded loss of CHF
18,400`. The note writes `CHF 18'400`, with an apostrophe.

Run, then eval.

**Checkpoint.** The run reports no failures at all, and `loss_amount` drops to
75%. Ask yourself why *that* is the right pair of outcomes, and read the detail
the scorer attaches to the verdict (you can get it by calling
`dossier.domain.scoring.score_field` yourself — see the solution).

Then try: does the span still match if you break it across two lines? If you
change the case of one word?

## Task 2 — abstention, done wrong twice

Variant: `replies-bare-null.json`. `PLAY-1002` abstains on `loss_amount` with no
reason, and gives a `severity` value with no source at all.

**Checkpoint.** Two fields drop, the document does not fail, and the two problems
are different ones:

- a `null` with no reason (R6.5) — abstention is a first-class answer, but only
  when it says why;
- a value with no source (R6.6) — the figure-without-evidence this system exists
  not to produce.

Compare this with exercise 05, where `PLAY-1002` abstained *properly* and scored
correct against a gold `null`. Same abstention, opposite verdicts, and the
difference is one field in the record.

## Task 3 — the one retry

Variant: `replies-retry.json`. `PLAY-1003` answers with a helpful sentence the
first time and with the declared schema the second.

Count the log lines before and after the run.

**Checkpoint.** Five model calls for four documents, and every score back at
100%. Then find `attempts` in the provenance record for `PLAY-1003` — it is the
one field in that file about what *happened* rather than what was asked.

Now swap the two rules in the variant file so the corrected answer comes second,
and run again. Read the rule file's comment before you do, and predict the result.

## Task 4 — a document that never produces an answer

Variant: `replies-never-valid.json`. `PLAY-1004` returns something schema-shaped
but wrong, twice.

**Checkpoint.** The run names the document, audits the other three, and exits
non-zero (R6.9). Check what landed in the cache for that document: nothing. A
failed document is a recorded failure, not a computed artifact, and caching it
would make one bad afternoon permanent (R6.1).

Run it a second time. The other three are served from cache; the failure is paid
for again, both calls. That is the honest price of not caching it.

Now try to score that run:

```bash
dossier eval incident-audit --gold gold/incidents
```

**Checkpoint.** It refuses, and what it says is worth thinking about. Scoring
reproduces a run from its manifest and cache (R7.10), and the manifest plans a
document that has no artifact. Decide what you think *should* happen when a run
that covered three of four documents is scored — and note that "score the three
and say so" and "refuse the lot" are both defensible, which is exactly the kind of
question that gets settled in a spec rather than in a patch.

---

## Done when

- four runs, four different failures, and you can name the rule behind each;
- you can say why an ungrounded field is not rescued by a correct value;
- you have an opinion, with reasons, about scoring a partially failed run.

**Next:** [07 · Calibrating a judge](../07-calibrating-a-judge/).
