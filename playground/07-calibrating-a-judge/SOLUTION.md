# 07 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

Terminal 1 — the stub answers both questions, judge rules first:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/07-calibrating-a-judge/resources/replies-judge.json \
  --replies playground/07-calibrating-a-judge/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Terminal 2:

```bash
mkdir -p playground/work/07/inbox/incidents playground/work/07/gold/incidents/samples
cp -r playground/07-calibrating-a-judge/solution/workspace/. playground/work/07/
cp playground/corpus/incidents/PLAY-100[1-4].md playground/work/07/inbox/incidents/
cp playground/07-calibrating-a-judge/resources/documents/PLAY-1005.md playground/work/07/inbox/incidents/
cp playground/07-calibrating-a-judge/resources/verified-answers/*.json playground/work/07/gold/incidents/
cp playground/07-calibrating-a-judge/resources/calibration-sample/root_cause.jsonl \
   playground/work/07/gold/incidents/samples/
cp playground/07-calibrating-a-judge/resources/judge-threshold/judge.yaml \
   playground/work/07/gold/incidents/judge.yaml
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/07/.env

cd playground/work/07
D=../../../.venv/bin/dossier
$D sync incident-audit && $D run incident-audit
$D calibrate incident-audit --gold gold/incidents
$D eval incident-audit --gold gold/incidents
```

---

## Task 1 — a field that needs a judge

```yaml
  root_cause:       {kind: free_text, judge: rubrics/root_cause.md}
```

```markdown
Is the stated root cause supported by the named document?
```

One sentence, and that is not laziness. The rubric is passed to the judge exactly
as written, and nothing `dossier` adds may raise or lower the standard it sets —
because a prompt tuned against the calibration sample measures the tuning rather
than the judge, and the figure it produces is the one your threshold would then
be set from (R7.11).

```console
$ dossier eval incident-audit --gold gold/incidents
5 documents · 4 fields · overall 100.0%
  loss_amount        100.0%
  resolution_date    100.0%
  severity           100.0%
  affected_systems   100.0%
  root_cause             -- never measured -- run `dossier calibrate`
```

Withheld rather than printed as zero, and named rather than omitted. Those are two
separate decisions and both are in R7.15: a zero would read as a field that was
always wrong, and a missing line would read as a field nobody verified.

## Task 2 — the sample, and why it is not the gold set

**A gold file says what the right value *is*. A sample line says whether a
*candidate* answer is supported by its document** — which is the question the
judge is asked, and the only question its agreement can be measured on.

The two artifacts have to be separate because a sample must be able to hold an
answer that is *wrong*:

```json
{"id": "rc-04", "document": "PLAY-1001.md",
 "answer": "The payment gateway vendor had an outage during the window.",
 "supported": false,
 "reason": "The note names the upgrade shipped the previous evening as the only change; it says nothing about a vendor outage.",
 "verified_by": "a.aleks", "verified_at": "2026-09-17"}
```

A gold file has nowhere to put that. It holds the verified answer, not a wrong
candidate and a verdict on it (R7.16).

**Twelve of twenty are supported**, so a judge that answered "supported" to
everything would score **60%**. That is the floor: any threshold at or below 0.60
passes a judge that decides nothing. This is not hypothetical — "agrees with
everything" is the most common way an LLM judge fails, and it is invisible in the
agreement figure unless your sample contains claims that ought to be rejected.
The repository's own evaluated rule R7.12 exists for exactly this: its judge must
mark a *planted* claim unsupported.

**The minimum sample is twenty**, from `MINIMUM_SAMPLE` in
`src/dossier/domain/judges.py`. Below it, agreement is not a weak measurement — it
is not a measurement, and the report must say "not measurable at this N" rather
than print a percentage. Ten of ten is 100% and means nothing.

## Task 3 — the threshold, and who writes it

```yaml
# root_cause: agreed by <your name> on <today's date>.
root_cause: 0.95
```

The argument, which is the part that matters:

- the judge measured **1.00** on twenty cases. Setting the bar at what one
  measurement happened to produce leaves no room for a single disagreement on the
  twenty-first case; 20 of 20 at N=20 supports a lower bound near 0.84, not 1.00;
- a judge that answers "supported" to everything scores **0.60** here, so the bar
  must be above that;
- 0.95 sits above the figure a useless judge reaches and below the figure a
  working one measured.

```console
$ dossier calibrate incident-audit --gold gold/incidents
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
```

```console
$ cat gold/incidents/calibrations/root_cause.json
{
  "agreement": 1.0,
  "judge_model": "openai:gpt-5.4-mini",
  "kappa": 1.0,
  "lower_bound": 0.8388748419471806,
  "prompt_hash": "1a7cde3cdf30c254ff747b7ab01f5266aa4b2fe867716286985e17f48de0eef2",
  "rubric_hash": "0443845ad5177750b66557482058e1750fca26147d5cf9139f3645a35c152b70",
  "sample_size": 20,
  "supported": {
    "agreed": 12,
    "cases": 12
  },
  "unsupported": {
    "agreed": 8,
    "cases": 8
  }
}
```

Three of these fields are the measurement's *provenance*: an agreement figure
without them says a judge agreed with a human, without saying which judge or on
what question. `judge_model`, `rubric_hash` and `prompt_hash` are what go stale in
task 5. `agreement` and `sample_size` are the measurement; the other four are
what the agreement does not say, and task 7 reads them.

`judge.yaml` was not touched, and cannot be: `calibrate` writes what it measured
and never the bar it is measured against (R7.14). In this repository an assistant
cannot write either file — the hook blocks any agent write under `gold/`, which is
why both arrived as proposals you had to accept.

## Task 4 — the field is reported

```console
$ dossier eval incident-audit --gold gold/incidents
5 documents · 5 fields · overall 100.0%
  loss_amount        100.0%
  resolution_date    100.0%
  severity           100.0%
  affected_systems   100.0%
  root_cause         100.0%   (4 judged)
```

**Five documents, four judged.** The fifth is `PLAY-1005`, whose note records the
cause as undetermined: gold says `null` and the run abstained with a reason, so
that verdict was decided deterministically by R7.3 before any judge was involved.

That ordering is the rule (R7.17): abstention and grounding are decided first, as
facts, and the judge decides only what is left. A judge asked about an abstention
would be asked to rule on an answer nobody gave.

The `(4 judged)` count exists so the line cannot lie by omission. Before R7.17,
`root_cause 50.0%` was a percentage over the abstention cases alone — a number the
whole gate was guarding and nothing produced.

```console
$ wc -l < /tmp/dossier-calls.jsonl
29
$ dossier eval incident-audit --gold gold/incidents > /dev/null
$ wc -l < /tmp/dossier-calls.jsonl
29
```

Twenty-nine calls: five extractions, twenty calibration cases, four judge
verdicts. The second eval asks **nothing**.

```console
$ find .dossier/cache/judge -type f ! -name '*.meta.json' | wc -l
4
$ cat .dossier/cache/judge/63/0e/630e8a50…
{"evidence":"The root cause section states exactly this.","supported":true}
$ cat .dossier/cache/judge/63/0e/630e8a50….meta.json
{
  "cache_key": "630e8a50f3e0900fc71c36971784adcf50271356394a6b2120fe5a07a47c4892",
  "candidate_hash": "22c663077971f31cc196bddacff73c39ddd3b05b415eb90c4b0ad66e76043294",
  "document_hash": "d7c5317a23938586cd2ce4d2778373d32693309ab91445e62120bbaa83211ac8",
  "dossier_version": "0.1.0",
  "judge_model": "openai:gpt-5.4-mini",
  "prompt_hash": "1a7cde3cdf30c254ff747b7ab01f5266aa4b2fe867716286985e17f48de0eef2",
  "rubric_hash": "0443845ad5177750b66557482058e1750fca26147d5cf9139f3645a35c152b70",
  "run_id": "20260917T210530Z-e6f4",
  "step": "judge"
}
```

A judge is a model, and a model is asked only on a cache miss — the boundary
promises that everything right of it is reproducible, "a judge included" (R0.10,
R7.18). Read that key: the candidate, the document, the judge, the rubric and the
wrapper. Change any one and it is a different question, deserving a different
verdict. Change the run id and it is not: `run_id` is in the record, not the key,
because two runs that produced the same candidate over the same document asked
the same question.

## Task 5 — four ways to lose the right to print a number

```console
$ # 1. a sentence appended to the rubric
  root_cause             -- calibration is stale: the rubric has changed since

$ # 2. model: changed to openai:gpt-4o-2024-08-06
  root_cause             -- calibration is stale: measured against openai:gpt-5.4-mini

$ # 3. threshold raised above what was measured (agreement 0.9 vs bar 0.95)
  root_cause             -- agreement 0.9 is below the agreed 0.95

$ # 4. the calibration file deleted
  root_cause             -- never measured -- run `dossier calibrate`
```

Four messages because they want four different fixes: a re-measure, a re-measure
against the new judge, a better judge or a bar somebody agrees to lower, and a
`dossier calibrate`. "No score" for all four would send someone to tune a prompt
when what is missing is gold data.

**What changed in case 1?** Not the judge, not the sample, not the threshold — the
*question*. Agreement was measured on one rubric and the judge is now being asked
another. Any change alone is enough, and staleness is checked **before** the bar,
because a figure measured against something else is not a figure to compare with
anything.

There is a third input to that check, and it is the subtle one: `prompt_hash`, the
wrapper `dossier` puts your rubric in (R7.19). An edit to that wrapper changes
what every judge is asked with no byte of your rubric moving — so a calibration
that recorded no prompt hash reads as stale rather than as fresh.

**At exactly the threshold?** Reported. The bound is inclusive: a judge measured
at precisely the agreed figure has met the agreed figure. It is one character in
`is_eligible` (`>=`), it is stated in R7.5 row 3, and it is exactly the kind of
thing that gets implemented as `>` by accident and then quietly withholds every
field measured at the bar.

## Task 6 — make the judge wrong, on purpose

```console
$ # rc-04 flipped in a copy of replies-judge.json, calibration and judge cache deleted
$ dossier calibrate incident-audit --gold gold/incidents
root_cause         95.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 76.4% · kappa 0.89 · supported 12 of 12 · unsupported 7 of 8
$ dossier eval incident-audit --gold gold/incidents | tail -1
  root_cause         100.0%   (4 judged)

$ # rc-01 flipped as well
$ dossier calibrate incident-audit --gold gold/incidents
root_cause         90.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 69.9% · kappa 0.79 · supported 11 of 12 · unsupported 7 of 8
$ dossier eval incident-audit --gold gold/incidents | tail -1
  root_cause             -- agreement 0.9 is below the agreed 0.95
```

One disagreement in twenty costs five points. That is the whole argument for not
setting the bar at 1.00: at N=20 a single hard case — and every corpus has them —
would withhold the field forever, and the pressure would then be on the *sample*
rather than on the judge. Which is the failure the hook in this repository exists
to prevent.

The eval still scores 100% with `rc-04` flipped, and that is right. `rc-04` is a
candidate in the sample, not one of the run's answers, so the judge was never
asked about it during the eval. Changing the judge's reply to it moved the
calibration and nothing else.

## Task 7 — what the agreement does not say

The three second lines, side by side:

```
100%   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
 95%   lower bound 76.4% · kappa 0.89 · supported 12 of 12 · unsupported 7 of 8
 90%   lower bound 69.9% · kappa 0.79 · supported 11 of 12 · unsupported 7 of 8
```

**Is the judge below your bar?** By its lower bound, yes: 83.9% is under 0.95,
and so is every lower bound this sample can produce. Twenty cases cannot show
better than 83.9%, however well the judge does. The gate compares the agreement
(R7.5), and the lower bound is reported beside it, never gated (R7.26 row 4).
Gating on it at 0.95 would withhold this field until the sample grew to 73 cases,
all of them agreed. That may be the right demand, and it may not. It is a
statement about how much evidence a score needs, which makes it a threshold, and
a threshold is agreed by a person (R7.11), not chosen by a tool.

The one figure a gold set *can* gate on, beside the agreement, is the unsupported
half: `unsupported: 0.875` under a state in `judge.yaml` (R7.30, R7.31). Here it
would change nothing, because `rc-04` leaves 7 of 8 caught, which is exactly
0.875, and the second flip is withheld on the agreement first. Exercise 10's task
5 shows a judge it does withhold: one that cleared its agreement bar.

**Which flip moved which half.** `rc-04` is a candidate the reviewer marked
unsupported, and flipping it let an invented cause through: `unsupported 7 of 8`.
`rc-01` is one the reviewer marked supported, and flipping it rejected a true
cause: `supported 11 of 12`. The first kind of mistake is the one that matters.
A judge that rejects a true cause costs a point of score. A judge that accepts an
invented one reports a wrong answer as right, which is the one outcome the judge
exists to prevent (R7.12). Agreement counts the two as the same five points; the
second line does not.

**A judge that says "supported" to everything** agrees on 12 of 20, which is 60%.
Its kappa is 0.00, and its counts are `supported 12 of 12 · unsupported 0 of 8`.
Every agreement it has is one chance would give it, and it catches nothing. Sixty
per cent reads like a weak judge. Kappa and the unsupported count say it is no
judge at all (R7.27 row 2, R7.28 row 2).

**All supported, and nothing to measure.** With no unsupported case, the
unsupported half has no rate: `no unsupported case`. Printing 8 of 8, or 0 of 0 as
100%, would credit the judge for a test it never sat. Kappa has nothing left to
correct for once the reviewer has used a single verdict, so it would come out 0 or
undefined whatever the judge did. `kappa not measurable` says so instead of
printing a number that looks like a measurement (R7.27 row 4, R7.28 row 4).

---

## What to take to your own project

- A judge's number is not evidence until the judge has been measured against
  human verdicts on the same question it will be asked.
- Measure against candidates and verdicts, not against the right answers. They
  are different artifacts because they answer different questions.
- Write down what a measurement was made against, and treat any change to it as
  stale. Judge, rubric, wrapper.
- Let the machine record what it measured; never let it move the bar.
- Put a floor under your threshold: whatever a judge that agrees with everything
  would score on your sample.
- Cache verdicts. A judge is a model, and the second look at the same evidence
  should be free.
