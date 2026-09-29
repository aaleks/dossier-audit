# 10 · Charts, screenshots and the `described` state

**You will build:** a pipeline over documents whose evidence is drawn rather than
written — an APM latency chart, a Grafana JVM panel, a Kibana error screenshot, a
throughput chart — running one model call per page, and a judge that is shown the
pages instead of a transcript.

**You will learn:** what `page_images` is and why it is one artifact, what a
`per_part` step does to keys and calls and retries, why a field can be neither
grounded nor ungrounded, why a judged field then needs two thresholds
measured against two samples, and why a document read page by page still gives
one answer per field.

**Uses the stub model as both the extractor and the judge.**

---

## Background, in one paragraph

Everything up to exercise 09 assumed the document could be turned into text. A
chart cannot. The figure on the panel in `PLAY-3001` appears in no sentence of
that document, and `PLAY-3006` is a screenshot with no text layer at all — a
string search over it finds nothing, because there is nothing to search.
`dossier` answers that in three pieces. A source converts to `page_images`, one
picture per page, as a single container (R8.11, R8.12). A step declares
`mode: per_part` and is run once per page, keyed and retried and cached per page
(R3.12). And a field whose span is in no text because the stage was reading
pictures is **`described`** — not a pass and not a failure, because the evidence
is on a page the model looked at and a string search is the wrong instrument for
it (R6.15). A judge decides it, and that judge is shown the pages (R7.21), which
is a different question from the one the text judge answers and so is measured
and gated on its own (R7.20, R7.22, R7.23).

---

## The documents

```
playground/corpus/observability/
  PLAY-3001-checkout-latency-apm.pdf        APM latency chart, p50/p95/p99
  PLAY-3002-jvm-heap-grafana.pdf            Grafana JVM memory panel
  PLAY-3003-kibana-error-spike.pdf          Kibana Discover: histogram and log rows
  PLAY-3004-batch-overlap-throughput.pdf    throughput bars and an error-rate line
  PLAY-3005-weekly-incident-review.pdf      four pages: summary, then three panels
  PLAY-3006-error-budget-screenshot.png     a screenshot. No text layer at all.
```

Each PDF carries a real text layer **and** a panel, and that pairing is the whole
point. The severity, the date, the affected systems and the root cause are
written in the text. The money figure is drawn on the panel and written in no
sentence anywhere. Same document, same run, two grounding states.

They are generated, not exported, by
`playground/toolkit/make_observability_docs.py` — reproducibly, so a snapshot
hash never changes for a document nobody edited.

## Task 1 — two sources, because two media types convert to different things

Write `sources.yaml` with the postmortems under `inbox/observability/` and the
screenshot under `inbox/screenshots/`. Give each one the `convert:` list it can
honestly supply: the PDFs make both `markdown` and `page_images`, the PNG makes
only `page_images`.

Then `dossier sync` and `dossier convert`.

**Checkpoint.**

```
observability  5 held · 10 converted · 0 cached
screenshots  1 held · 1 converted · 0 cached
```

Ten from five. Say why before reading on — and then say what would happen if you
added `markdown` to the screenshot source, and which rule would stop it.

## Task 2 — a step that is shown a page

Write `pipelines/observability-audit/pipeline.yaml` with one step:
`input: documents@page_images`, `mode: per_part`, `output:` a five-field
declaration. Then write the prompt.

The prompt is the surprising part. A `per_part` step reads one input and that
input is a container of pictures, so **the prompt carries no document text at
all** — `{{documents@page_images}}` renders empty, because a container of
pictures is not something a placeholder can hold (R8.11). Everything the model
knows about the document it reads off the page, which is why every page of these
documents prints its own key and page number in the header.

Run it with the stub (`resources/replies.json`), then read the call log.

**Checkpoint.**

```
  extract: 6 document(s) · 0 from cache · 0 failed · 10 described
```

and nine calls, each carrying exactly one picture, each with a prompt of exactly
the same length. Six documents, nine calls: find the document that accounts for
the difference.

Then the question this exercise turns on: **if every call has the same prompt,
how does the stub tell them apart?** Open `resources/replies.json` and see.

## Task 3 — grounded, described, and the difference between them

Open `runs/<id>/extract/PLAY-3001-checkout-latency-apm.pdf/page-001.json`. Five
fields, all from one call, all citing the same document. Four of them are
grounded and one is described.

- Which one, and what is different about the span it quotes?
- `PLAY-3006` produces five described fields out of five. Why is that not a
  defect in the document?
- `source.page` is `null` on a described field and a number on a grounded one.
  Work out why, and find the rule (R6.14).

Then open the `.meta.json` beside it and find the input whose role is `part`.
Its hash begins with the twelve characters the answering rule gave as its
`image`. That is not a coincidence — it is one fact written down in two places:
the page is what makes this call different from every other call of this step.

## Task 4 — the third state needs a second bar

Add `root_cause: {kind: free_text, judge: rubrics/root_cause.md}` to the field
declaration, write the rubric, and name the gold set in `pipeline.yaml`
(`gold: gold/observability`).

Now write `gold/observability/judge.yaml` with **one threshold per state** and
run `dossier run` before you write it.

**Checkpoint.** The run stops before it renders a page:

```
pipeline.yaml: field 'root_cause' is produced by a per_part step, which can
answer it from a page image, and .../judge.yaml declares no 'described'
threshold for it.
```

Read `resources/judge-threshold/judge.yaml`, including the reasoning, decide
whether you agree with 0.95 and 0.90, and write your own with your name and
today's date. Then copy both samples from `resources/calibration-sample/` into
`gold/observability/samples/` and calibrate.

**Checkpoint.** Two files under `calibrations/`, one per state. Before task 5,
answer: why is the described bar *lower* than the grounded one, and what would
you have to believe to set them equal?

## Task 5 — the field is reported, and how it is lost

Eval before calibrating and after. Then run eval twice and watch the call log:
not one extra call, because a verdict is an artifact keyed on its evidence — and
for a described verdict that evidence is the pages, so the same candidate judged
against a different rendering is a different entry (R7.18, R7.21).

Now make the vision judge wrong on purpose. In a copy of
`resources/replies-judge.json`, flip the `supported` values for **two** described
cases the reviewer marked not supported, `rd-17` and `rd-20`. Point the stub at the
copy, delete `calibrations/` and `.dossier/cache/judge/`, and calibrate again.

**Checkpoint.** 90.0% — exactly the bar, and the field is still reported. Now read
the line under the described judge's agreement: `unsupported 6 of 8`. It cleared
its bar while letting through two causes nobody wrote down. That half can have a
bar of its own (R7.30). Agree one in `gold/observability/judge.yaml`:

```yaml
root_cause:
  grounded: 0.95
  described: {agreement: 0.90, unsupported: 0.875}
```

**Checkpoint.** Eval again, and the field is withheld:

```
  root_cause             -- described: unsupported 6 of 8 (75.0%) is below the agreed 87.5%
```

Why is 0.875 a share and not "at most one"? What would 7 of 8 do, and a sample
with only seven unsupported cases, all caught? (R7.31.)

Flip a third, `rd-19`, which the reviewer marked supported, and the field is
withheld on its agreement before the unsupported half is looked at:

```
  root_cause             -- described: agreement 0.85 is below the agreed 0.9
```

Two things to notice, and both are the rule working. The grounded judge still
measures 100% and is untouched: one state failing does not implicate the other's
figure. And the whole field is withheld anyway, because a field reported on the
strength of the half of its verdicts that happened to clear would be a number
nobody can act on (R7.23).

## Task 6 — a run of pages replays

```bash
dossier run --replay runs/<id>/
```

**Checkpoint.** Nine artifacts reproduced, no model calls, written under
`runs/<id>/replays/`. Nine, not six: a replay recomposes the key each page was
written under, and a key without the part in it is a key no run ever wrote — which
is what made every `per_part` run irreproducible before R4.14.

Then break it deliberately: delete the `png-pages` container from
`.dossier/cache/convert/` and replay again. Two things to check, and the second
is the one that matters:

- the message names the step, its mode, and the document whose pages are gone;
- **nothing is written at all** — not even the eight artifacts it could still
  reproduce. Find the rule that says so and the sentence explaining why a
  partial replay is worse than none (R0.12).

## Task 7 — four pages, one answer

`PLAY-3005` is read in four calls, and nothing stops two of them answering the
same field. Page 2's panel carries the week's worst moment, `Peak p99 for the
week:  4.2 s at 09:04 on 2026-09-02`. A model asked for `incident_date` with only
that page in front of it has a date right there. It is not the date the review
was resolved.

Make the stub read the page that way. Write `pages.json` in the workspace with
one rule, for page 2's picture:

```json
{"rules": [{
  "image": "5ae908cb70c5",
  "reply": {"document": "PLAY-3005-weekly-incident-review.pdf", "fields": [
    {"field": "incident_date", "value": "2026-09-02",
     "source": {"document": "PLAY-3005-weekly-incident-review.pdf",
                "span": "Peak p99 for the week:  4.2 s at 09:04 on 2026-09-02"}}]}
}]}
```

Restart the stub with `--replies pages.json` between the judge's file and
`replies.json`. The first rule that matches wins, so an override goes before the
file it overrides. The stage cache still holds page 2's empty answer under the
same key: same prompt, same page, same model. Delete `.dossier/cache/stage/`,
then run and eval.

**Checkpoint.** Whatever state task 5 left the judge in, the date's lines read:

```
  incident_date       83.3%   <- weakest
    PLAY-3005-weekly-incident-review.pdf page-002.png: '2026-09-02' does not match '2026-09-08'
```

- 83.3% is five documents of six. Page 1 still gave the right date. Why is the
  document wrong rather than half right? (R7.48)
- Before 2026-09-28 the same run printed 85.7% for this field. Work out what it
  was counting. (R7.46)
- The run said `11 described`, one more than before. Why did no grounding check
  catch a date from the wrong incident, and what did?

Now make page 2 honest. Replace its field with
`{"field": "incident_date", "value": null, "reason": "the panel shows the week, not the day it was resolved"}`.
The stub reads its files again on every request, so it needs no restart. Delete
the stage cache, then run and eval.

**Checkpoint.** `incident_date 100.0%`. Page 1 answered, and a page that says it
cannot tell is not an answer for its document (R7.47). Before the same change,
that abstention was a miss against the verified date. That is why task 2's
prompt tells a page to leave a field out rather than say so.

Last, take the date away from every page. Replace page 2's rule in `pages.json`
with one for page 1's picture, `a2d2bbd691ef`: copy it from `replies.json` and
drop its `incident_date`. With the override gone, page 2 falls back to its empty
answer, so no page of `PLAY-3005` gives the date.

**Checkpoint.**

```
  incident_date       83.3%   <- weakest
    PLAY-3005-weekly-incident-review.pdf not answered; gold states '2026-09-08'
```

A field the verified answers state and no page gave is a miss, like any other
the run got wrong (R7.50). What did the field read before, when a run's silence
was left out of the count?

Each of the three runs is nine calls in the log, and eval adds none: `root_cause`
did not change, so its verdicts are still in the judge cache. Had a page given a
second root cause, the judge would have been asked about each distinct answer,
and one it did not support would fail the document (R7.49).

Take `pages.json` off the stub's command line before the next exercise.

---

## Done when

- a chart is evidence: a figure that appears in no sentence is extracted,
  described, judged and scored;
- you can say what a `per_part` step does to calls, keys, retries and replays,
  and point at the part hash in a provenance record;
- you can explain to someone else why `described` is neither a pass nor a
  failure, and why it needs its own threshold and its own sample;
- you can say how a field four pages answered is scored, and read the page a
  miss came from off the eval.

**Next:** [12 · A dataset, and the change gate](../12-a-dataset-and-the-change-gate/),
which stays offline like this one. [11 · A real Jira on your
machine](../11-a-real-jira-on-your-machine/) is the optional detour that needs
Docker. Or stop here and open `specs/006-output-schemas.md` and
`specs/008-conversion.md` to read what you have just been running.
