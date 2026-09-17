# 06 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

```bash
mkdir -p playground/work/06/inbox/incidents playground/work/06/gold/incidents
cp -r playground/06-grounding-abstention-and-the-one-retry/solution/workspace/. playground/work/06/
cp playground/corpus/incidents/PLAY-100[1-4].md playground/work/06/inbox/incidents/
cp playground/06-grounding-abstention-and-the-one-retry/resources/verified-answers/*.json \
   playground/work/06/gold/incidents/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/06/.env

cd playground/work/06 && ../../../.venv/bin/dossier sync incident-audit
```

Then, per task, restart the stub with that task's variant in front and
`rm -rf .dossier/cache/stage runs` before each run.

---

## Task 1 — a right answer with a wrong citation

```console
$ dossier run incident-audit
  extract: 4 document(s) · 0 from cache · 0 failed

$ dossier eval incident-audit --gold gold/incidents
4 documents · 4 fields · overall 93.8%
  loss_amount         75.0%   <- weakest
  resolution_date    100.0%
  severity           100.0%
  affected_systems   100.0%
```

**The run reports no failure, and the score drops.** That pairing is deliberate. A
field with a plausible value and no evidence has not made the *run* fail — the
stage got a well-formed answer for every document — it has produced a finding,
and findings are scoring's business (spec 006's four verdicts: `valid`,
`abstained`, `ungrounded`, `invalid`).

The verdict and the reason, asked of the domain directly — no workspace, no
model, milliseconds:

```console
$ python - <<'PY'
from dossier.domain.grounding import check_field, locate_span
from dossier.domain.schemas import FieldRecord, Evidence
from dossier.domain.scoring import score_field, FieldKind, GoldField
from pathlib import Path

text = Path("playground/corpus/incidents/PLAY-1001.md").read_text()
rec = FieldRecord(field="loss_amount", value=18400.0, currency="CHF",
                  source=Evidence(document="PLAY-1001.md", span="a recorded loss of CHF 18,400"))
check = check_field(rec, input_documents={"PLAY-1001.md": text})
print(check.verdict.value, "|", check.detail)
print(score_field(record=rec, gold=GoldField(value=18400.0, currency="CHF"),
                  check=check, kind=FieldKind.AMOUNT).detail)
PY
ungrounded | loss_amount: span not found in PLAY-1001.md (R6.4).
ungrounded: the value may be right, and nothing in the document shows it
```

That second line is R7.4 in one sentence. The grounding verdict is checked
*before* any comparison with gold, so a value that happens to match cannot rescue
a field with no evidence behind it — otherwise the whole check would be
decorative, passing exactly when it did not matter.

Being able to run that snippet is worth as much as the exercise. `check_field` and
`score_field` are pure functions in `domain/`: they take what they need and
answer. That is what makes these rules provable in milliseconds without a
workspace, and it is the first thing to copy into your own project.

The two follow-up questions:

```console
across a line break: True
wrong case:          False
```

Whitespace is normalised on **both** sides, so a span the converter flattened out
of a table, or one broken across two lines in the source, still matches — a
converter is as likely to be the source of a difference as the model is, and
normalising only the model's side would fail honest citations.

Case is compared exactly, deliberately: case-folding would let a field citing
`MAJOR` claim support from a document that says `major`, and a span is meant to be
what the document says rather than an approximation of it. The code says that if
this proves too strict against real converted text, it is a spec conversation
rather than a quiet relaxation — which is the same instinct as exercise 04's
amendment.

## Task 2 — abstention, done wrong twice

```console
$ dossier eval incident-audit --gold gold/incidents
4 documents · 4 fields · overall 87.5%
  loss_amount         75.0%   <- weakest
  resolution_date    100.0%
  severity            75.0%   <- weakest
  affected_systems   100.0%
```

Both records are `invalid`, and the messages say which problem is which:

```
loss_amount: value is null with no reason. Abstention must say why it abstained (R6.5).
severity: has a value and no source. A figure without evidence is the thing this system
exists not to produce (R6.6).
```

Put beside exercise 05, this is the sharpest lesson in spec 006. There,
`PLAY-1002` abstained on `loss_amount` **with** a reason, gold said `null`, and it
scored **correct**. Here the same abstention with the reason removed scores
incorrect. The difference is one field in one record, and it is the difference
between "the document does not state it" and a field the model forgot.

Note again what did not happen: the document did not fail. Two fields have
findings, two do not, and the run carries on. Blast radius is chosen per failure
type throughout this codebase, and it is always the smallest one that is still
honest.

## Task 3 — the one retry

```console
$ wc -l < /tmp/dossier-calls.jsonl        # before
0
$ dossier run incident-audit
  extract: 4 document(s) · 0 from cache · 0 failed
$ wc -l < /tmp/dossier-calls.jsonl        # after
5

$ dossier eval incident-audit --gold gold/incidents
4 documents · 4 fields · overall 100.0%
```

Five calls for four documents. `PLAY-1003`'s first answer —

```
The incident was caused by a firewall change and cost CHF 61'250.
```

— is not the declared schema, so the stage asked once more with a correction
block prepended:

```
<validation_error>
Your previous answer did not validate against the required schema. Correct it and
return only the corrected answer.
{the validation error}
</validation_error>
```

and the second answer validated. The provenance record keeps the count:

```json
{"attempts": 2, "cache_key": "…", "step": "extract", "run_id": "…", …}
```

**One retry, and exactly one** (R6.2). A model that cannot produce the shape twice
will not produce it on the fifth attempt either, and an unbounded retry loop turns
a bad prompt into a bill.

Two details worth carrying away:

- The correction text is a named constant in
  `src/dossier/application/extract.py`, not an inline string, precisely because
  it is **not** in any cache key: a stage key covers the prompt *template*, so
  editing the correction invalidates nothing. Naming it means an edit shows up in
  a diff instead of staying buried in a function body.
- Swapping the two rules in the variant file — corrected answer second — makes
  the stub answer with prose both times, because the first rule matches both the
  original prompt and the retry. That is task 4's situation, reached by a
  different route, and it is what a real model looks like when a prompt cannot be
  satisfied.

## Task 4 — a document that never produces an answer

```console
$ dossier run incident-audit
run 20260917T210642Z-595a · …
  extract: 4 document(s) · 0 from cache · 1 failed
    extract failed on PLAY-1004.md
exit 1
```

Six calls: one each for three documents, two for `PLAY-1004`. The other three
documents are audited, the failure is named, and the command exits non-zero —
either kind of failure means this audit covered less than the corpus, and a zero
exit would let anything reading `$?` quote it as clean (R6.9).

Nothing was cached for it:

```console
$ find .dossier/cache/stage -type f ! -name '*.meta.json' | wc -l
3
```

Three artifacts for four documents. A failed document is a recorded failure, not a
computed artifact (R6.1, R5.8) — so a second run serves three from cache and pays
for the two failed calls again. That is deliberate: caching a failure would make
one bad afternoon permanent, and a transient model problem would look identical to
a permanent one forever after.

Scoring that run:

```console
$ dossier eval incident-audit --gold gold/incidents
step 'extract' has no cached artifact for 'PLAY-1004.md' at a4eff980d6dd…; this run cannot
be reproduced from this workspace, and nothing has been substituted for it.
exit 2
```

**A run with one failed document cannot be scored at all.** The chain is
consistent: `eval` reproduces a run from its manifest and cache exactly as
`--replay` does (R7.10), the manifest plans four documents, one has no artifact,
and a replay may fail but may never substitute other content (R4.7).

Whether that is the *right* outcome is a genuine design question, and it is
deliberately left open here:

- **Refuse the lot** — today's behaviour. A score is a claim about a run, and a
  run that cannot be reproduced cannot be scored honestly.
- **Score what reproduced, and say what did not** — arguably more useful: three
  documents' worth of evidence is still evidence, provided the report never lets
  you forget the fourth. That is R7.15's shape for withheld fields, applied to
  documents.

Notice which door this repository would go through: neither is implemented on a
hunch. It is a rule in spec 007 with examples, a counter-example, and a test named
after it — or it stays as it is. That is the whole working agreement in one
decision.

---

## What to take to your own project

- Make evidence checkable without a model. A string search you can run in
  milliseconds is worth more than a judgement you have to calibrate.
- Check evidence *before* comparing values, or the check passes exactly when it
  does not matter.
- Give abstention a first-class shape, and require it to say why.
- Retry once, name the constant, and keep the retry out of the cache key.
- Never cache a failure.
