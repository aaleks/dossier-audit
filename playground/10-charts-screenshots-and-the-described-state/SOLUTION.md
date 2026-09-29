# 10 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

Terminal 1 — the stub answers both questions, judge rules first:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/10-charts-screenshots-and-the-described-state/resources/replies-judge.json \
  --replies playground/10-charts-screenshots-and-the-described-state/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Terminal 2:

```bash
E=playground/10-charts-screenshots-and-the-described-state
mkdir -p playground/work/10/inbox/observability playground/work/10/inbox/screenshots \
         playground/work/10/gold/observability/samples
cp -r $E/solution/workspace/. playground/work/10/
cp playground/corpus/observability/PLAY-300[1-5]*.pdf playground/work/10/inbox/observability/
cp playground/corpus/observability/PLAY-3006*.png     playground/work/10/inbox/screenshots/
cp $E/resources/verified-answers/*.json      playground/work/10/gold/observability/
cp $E/resources/calibration-sample/*.jsonl   playground/work/10/gold/observability/samples/
cp $E/resources/judge-threshold/judge.yaml   playground/work/10/gold/observability/judge.yaml
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/10/.env

cd playground/work/10
D=../../../.venv/bin/dossier
$D sync observability-audit && $D convert observability-audit && $D run observability-audit
$D calibrate observability-audit --gold gold/observability
$D eval observability-audit --gold gold/observability
```

This exercise needs the PDF extra: `uv sync --all-extras`, or
`pip install -e ".[pdf]"`. Without it `pdf-markdown` and `pdf-images` are still
registered, because `dossier` declares their entry points itself, but neither
can read a page. Each PDF fails on its own, and the screenshot converts:

```console
$ dossier convert observability-audit        # dossier installed without [pdf]
observability  5 held · 0 converted · 0 cached · 5 failed
    PLAY-3001-checkout-latency-apm.pdf: ValueError: pdf-markdown needs the 'pdf' extra: install dossier[pdf]
    PLAY-3002-jvm-heap-grafana.pdf: ValueError: pdf-markdown needs the 'pdf' extra: install dossier[pdf]
    …
screenshots  1 held · 1 converted · 0 cached
cache updated · 1 converted · 0 cached
exit 1
```

---

## Task 1 — two sources, because two media types convert to different things

```yaml
sources:
  - id: observability
    type: folder
    path: inbox/observability/
    convert: [markdown, page_images]

  - id: screenshots
    type: folder
    path: inbox/screenshots/
    convert: [page_images]
```

```console
$ dossier sync observability-audit
observability  0 known · 0 changed · 5 new -> 5 fetched
screenshots  0 known · 0 changed · 1 new -> 1 fetched
ledger updated · 6 new snapshots · 0 tombstoned

$ dossier convert observability-audit
observability  5 held · 10 converted · 0 cached
screenshots  1 held · 1 converted · 0 cached
cache updated · 11 converted · 0 cached
```

**Ten from five** because a declared conversion is one artifact per (document,
kind), and these five documents declare two kinds. `PLAY-3005` has four pages and
still contributes exactly two artifacts: its `page_images` is **one** container
holding four PNGs, not four artifacts. R8.11 says why — forty keys for a
forty-page document would let a converter version bump invalidate its pages one
at a time, and leave a document with nineteen old pages and twenty-one new ones.

Asking the screenshot source for `markdown` as well stops the run:

```console
$ dossier convert observability-audit
1 document(s) have no converter:
  PLAY-3006-error-budget-screenshot.png (image/png): nothing converts ('image/png',
  'markdown'). Claimed pairs: ['(application/pdf, markdown)', '(application/pdf,
  page_images)', '(application/vnd.dossier.confluence-page+json, markdown)',
  '(application/vnd.dossier.jira-issue+json, markdown)', '(image/jpeg, page_images)',
  '(image/png, page_images)', '(text/csv, markdown)', '(text/html, markdown)',
  '(text/markdown, markdown)', '(text/plain, markdown)']. A converter is added by
  installing a package that declares a dossier.converters entry point.
```

That is R8.24. A kind written in `convert:` is one the installation has to
supply, and one it cannot is known before the source converts anything, so the
command stops with exit 2 rather than reporting one document failed. The pairs
it lists are the honest answer: no converter claims to turn a PNG into text, and
an image left to the default table resolves to `page_images` (R8.10). The fix is
the `convert:` list, not a converter.

## Task 2 — a step that is shown a page

```yaml
steps:
  - id: extract
    prompt: prompts/01_extract.md
    input: documents@page_images
    mode: per_part
    output: schemas/observation.yaml
```

```console
$ dossier run observability-audit
run 20260919T121417Z-9295 · .../runs/20260919T121417Z-9295/manifest.json
  extract: 6 document(s) · 0 from cache · 0 failed · 10 described
```

Six documents, **nine calls** — `PLAY-3005` has four pages and each one is its
own call, its own key, its own retry budget and its own cache entry (R3.12).
Summarised from the stub's call log, one line per call:

```
images  sha256             chars  first line
1       40b7b9b93532d5de   917    You are shown **one page** of an incident document…
1       4fb16bec73acb276   917    You are shown **one page** of an incident document…
1       b9c3566ad7e0332f   917    You are shown **one page** of an incident document…
…
```

Every prompt is 917 characters, because it is the same prompt. A `per_part` step
reads one input and that input is a container of pictures, so
`{{documents@page_images}}` renders to nothing at all: the pages reach the model
as image parts beside the message (R9.16), never as a substitution.

**So the stub cannot tell two calls apart by their text, and does not try.** Each
rule in `resources/replies.json` matches on the sha256 of the picture:

```json
{
  "_comment": "PLAY-3005-weekly-incident-review.pdf · page 4 of 4 · the error panel…",
  "image": "b4599c6cc3e3",
  "reply": {"document": "PLAY-3005-weekly-incident-review.pdf", "fields": [...]}
}
```

That is not a workaround. It is the same fact the stage key states — the part is
in the key by content hash and nothing else about it is — said in the one other
place that has to know which page it is looking at.

## Task 3 — grounded, described, and the difference between them

`runs/<id>/extract/PLAY-3001-checkout-latency-apm.pdf/page-001.json`, one call,
five fields:

```
incident_date    = '2026-09-02'                          page 1     Resolved: 2026-09-02
severity         = 'critical'                            page 1     Severity: critical
affected_systems = 'checkout-service, payments-gateway'  page 1     Affected systems: …
root_cause       = 'The canary released at 08:04 …'      page 1     Root cause: the canary …
revenue_at_risk  = 84600.0                               page None  Revenue at risk over the window:  CHF 84'600
```

Four grounded, one described, and the difference is entirely in the document.
The first four spans are sentences in the PDF's text layer, so a string search
finds them (R6.4). The fifth is drawn on the panel and written in no sentence
anywhere, so the search fails — and because this stage was handed the page as a
picture, that failure is `described` rather than `ungrounded` (R6.15). It is
neither a pass nor a failure: counting it as a failure would score honest visual
evidence as fabrication, and counting it as a pass would let an unverifiable
claim through as a checked one.

`PLAY-3006` produces five described fields out of five:

```
incident_date    = '2026-09-11'                      page None   Resolved: 2026-09-11
severity         = 'major'                           page None   Severity: major
affected_systems = 'checkout-service, edge-gateway'  page None   Affected systems: …
root_cause       = 'The error budget for checkout…'  page None   Root cause: the error budget …
revenue_at_risk  = 53100.0                           page None   Revenue at risk over the window:  CHF 53'100
```

That is not a defect in the document. It is a screenshot: there is no text layer,
so there is nothing for a string search to succeed or fail against, and every
field it carries has to be decided by looking.

`source.page` follows from the same thing. The page is **derived** from the
anchor the located span sits after, never taken from the model's word for it
(R6.14) — so a span that cannot be located has no page, and `null` is the honest
answer rather than a fabricated `1`.

The provenance record beside the artifact closes the loop:

```json
"inputs": [
  {"role": "documents@page_images", "path": "documents@page_images/PLAY-3005-…pdf",
   "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
  {"role": "part", "path": "part/PLAY-3005-…pdf/page-004.png",
   "hash": "b4599c6cc3e3f2c20748cdb21099ab8dd512fe3c366f337882e6a1ae23d47f48"}
]
```

The part's hash is the string the stub's rule matched on. And the *other* hash is
`e3b0c442…`, which is the sha256 of the empty string: the text substitution for a
container of pictures, holding exactly what it says it holds.

## Task 4 — the third state needs a second bar

With `gold: gold/observability` named in `pipeline.yaml`, a judge.yaml that
declares one number is refused as the pipeline loads — before a page is rendered
and before a model is reached:

```console
$ dossier run observability-audit
pipeline.yaml: field 'root_cause' is produced by a per_part step, which can answer
it from a page image, and .../gold/observability/judge.yaml declares no 'described'
threshold for it. A described verdict gated on a figure measured against text is
not gated (R6.15, R7.20).
```

A scalar is not wrong in general — it still means `grounded:` alone, so every
gold set written before there were two states reads unchanged. It is wrong *here*,
because this pipeline can reach a judged verdict in a state that number was never
measured for.

```yaml
root_cause:
  grounded: 0.95
  described: 0.90
```

Two samples, one per state, and `calibrate` measures each against its own:

```console
$ dossier calibrate observability-audit --gold gold/observability
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
root_cause.described 100.0% agreement over 20 cases · openai:gpt-5.4-mini
                     lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
```

Each judge gets its own second line: the lower bound, the kappa and the two halves
that its agreement does not show (R7.29, and exercise 07's task 7). The described
line is indented further because its name is longer; each second line starts
where its own agreement figure does.

```console
$ ls gold/observability/calibrations/
root_cause.described.json
root_cause.json
```

The grounded judge keeps the unqualified name, which is the same bargain the
scalar threshold makes (R7.20, R7.22). Remove the described sample and nothing is
guessed:

```console
$ dossier calibrate observability-audit --gold gold/observability
root_cause.described: no calibration sample at .../samples/root_cause.described.jsonl.
A judge cannot be measured against a sample nobody has written (R7.14, R7.16).
```

**Why the described bar is lower.** Reading a page and then judging it is the
harder job, and that is measured rather than assumed: dossier's own vision judge
agrees with a human on 21 of 22 visual cases, twice, and the case it misses is one
where a hypothesis table's `Verdict` column reads as an assertion (R7.24). To set
the two equal you would have to believe that judging a rendering is exactly as
reliable as judging a transcript — and then accept that the first genuine
disagreement about a chart withholds the field. Both bars clear the same floor:
twelve of twenty cases in each sample are supported, so a judge answering
"supported" to everything scores 0.60 and passes neither.

## Task 5 — the field is reported, and how it is lost

```console
$ dossier eval observability-audit --gold gold/observability      # before calibrating
6 documents · 4 fields · overall 100.0%
  incident_date      100.0%
  severity           100.0%
  affected_systems   100.0%
  revenue_at_risk    100.0%
  root_cause             -- never measured -- run `dossier calibrate`
```

`revenue_at_risk` scores 100% while being described on every document, which is
worth a moment: the grounding state and the score are different questions. The
value is compared with the verified answer as any amount is (R7.2); what
`described` decides is whether the *evidence* for it was checkable by string
search, and a judge answers that separately.

```console
$ dossier eval observability-audit --gold gold/observability      # after
6 documents · 5 fields · overall 100.0%
  ...
  root_cause         100.0%   (6 judged)
```

A second eval adds **no calls at all**. Counting the log, the whole session is
55 calls:

```
total        55
with images  30     9 stage calls + 20 described calibration cases + 1 eval verdict
text only    25    20 grounded calibration cases + 5 eval verdicts
```

One picture-carrying verdict in eval, because `PLAY-3006` is the one document
whose `root_cause` is described. Its verdict is keyed on the pages rather than on
a transcript, so the same candidate judged against a different rendering would be
a different entry rather than a cache hit (R7.18, R7.21).

Now the judge is made wrong on purpose. Two described verdicts are flipped,
`rd-17` and `rd-20`, both of which the reviewer marked not supported; then
`calibrations/` and `.dossier/cache/judge/` are deleted and the judge is
recalibrated:

```console
$ dossier calibrate observability-audit --gold gold/observability
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
root_cause.described 90.0% agreement over 20 cases · openai:gpt-5.4-mini
                     lower bound 69.9% · kappa 0.78 · supported 12 of 12 · unsupported 6 of 8

$ dossier eval observability-audit --gold gold/observability
  root_cause         100.0%   (6 judged)
```

Exactly at the bar, and reported: the bound is inclusive, and that is a decision
rather than an accident — a threshold somebody agreed to is a threshold that may
be met. Look at the second line, though. At the bar, this judge has let two claims
through that the reviewer marked not supported (`unsupported 6 of 8`), and its
kappa is 0.78. Exercise 07's judge was also at 90% (one miss in each half) and
had a kappa of 0.79. The agreement is the same; what the judge gets wrong is not
(R7.28).

So agree a bar for that half, beside the agreement bar (R7.30):

```console
$ # described: {agreement: 0.90, unsupported: 0.875} in judge.yaml
$ dossier eval observability-audit --gold gold/observability
6 documents · 4 fields · overall 100.0%
  ...
  root_cause             -- described: unsupported 6 of 8 (75.0%) is below the agreed 87.5%
```

The agreement still clears its bar. The field is withheld on the half the judge
exists for: two of eight invented causes accepted (R7.31). The message names the
state, the count, the share and the bar, because the fixes differ. A judge below
the bar wants a better judge. A sample with fewer than eight unsupported cases
would be withheld as not measurable, never as 100%, and wants more cases in the
sample. And a calibration from before the halves were counted wants a
`dossier calibrate`.

**Why a share.** 0.875 is seven of eight: out of R7.11's eight unsupported cases,
no more than one let through. Written as "at most one", it would hold a sample of
forty unsupported cases to 97.5%. Written as a share, it holds every sample to the
same rate. 7 of 8 meets it, because the bound is inclusive, as R7.5's is.

Flip a third, `rd-19`, which the reviewer marked supported. The agreement is
checked first, so the field is withheld on it before the unsupported half is
looked at:

```console
$ dossier calibrate observability-audit --gold gold/observability
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
root_cause.described 85.0% agreement over 20 cases · openai:gpt-5.4-mini
                     lower bound 64.0% · kappa 0.68 · supported 11 of 12 · unsupported 6 of 8

$ dossier eval observability-audit --gold gold/observability
6 documents · 4 fields · overall 100.0%
  ...
  root_cause             -- described: agreement 0.85 is below the agreed 0.9
```

Two things, and both are R7.23 working. The grounded judge is untouched at 100%
and says so — one state failing does not implicate the other's figure, because
they were measured apart. And the **whole field** is withheld even so: a field
reported on the strength of the half of its verdicts that happened to clear would
be a number nobody could act on, and the message names the state so the reader
knows which sample to go and look at.

## Task 6 — a run of pages replays

```console
$ dossier run --replay runs/20260919T121417Z-9295/
replayed 20260919T121417Z-9295 · observability-audit
  extract: 9 artifact(s) from cache
9 artifact(s) reproduced · no model calls · written to
runs/20260919T121417Z-9295/replays/20260919T121428Z-5696/
```

Nine, not six. A replay recomposes the key each call was written under, and for a
`per_part` step that key holds the part. Leaving it out built a key no run had
ever written, so every `per_part` run was irreproducible — and `dossier eval`,
which scores a replay, could score none of them. That is R4.14, and it was found
by nobody until a slice went looking.

Delete the `png-pages` container from `.dossier/cache/convert/` and replay again:

```console
$ dossier run --replay runs/20260919T121417Z-9295/
step 'extract' is mode: per_part and no parts could be reproduced for
'PLAY-3006-error-budget-screenshot.png'; this run cannot be reproduced from this
workspace, and nothing has been substituted for it.
```

Exit 2, and `runs/<id>/replays/` gains nothing — not even the eight artifacts it
could still have reproduced. R0.12: a replay that wrote what it could would
produce a directory that looks like a reproduction and is not one, and the
difference would be visible only to somebody who counted the files.

`dossier convert` puts the container back, and the replay succeeds again.

## Task 7 — four pages, one answer

The stub runs with the judge's own replies, as at the top of this file, so
`root_cause` is reported. `pages.json` goes between the two files, because the
first rule that matches wins:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies $E/resources/replies-judge.json \
  --replies playground/work/10/pages.json \
  --replies $E/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

With page 2 reading the week's peak as the incident's date:

```console
$ rm -rf .dossier/cache/stage/
$ dossier run observability-audit
run 20260929T052619Z-3d4f · .../runs/20260929T052619Z-3d4f/manifest.json
  extract: 6 document(s) · 0 from cache · 0 failed · 11 described · tokens not reported

$ dossier eval observability-audit --gold gold/observability
6 documents · 5 fields · overall 96.7%
  incident_date       83.3%   <- weakest
    PLAY-3005-weekly-incident-review.pdf page-002.png: '2026-09-02' does not match '2026-09-08'
  severity           100.0%
  affected_systems   100.0%
  revenue_at_risk    100.0%
  root_cause         100.0%   (6 judged)
```

**Why the document is wrong, not half right.** A field is correct for a
document only when every page that gave it a value is correct (R7.48). The
review has one incident date. A document that gave two has not given it, and
crediting page 1 would score a run that answers every date on every page as
always right. The miss names `page-002.png`, which is where to look.

**What 85.7% was counting.** Records, not documents: six dates, one per
document, plus page 2's second date for `PLAY-3005`. That is six right of
seven. Counted that way, a four-page document that repeats a field on every page
outweighs a one-page screenshot four to one. Now a field is one verdict per
document, however many pages gave it (R7.46).

**Why no grounding check caught it.** The date is drawn on page 2's panel and
written in no sentence, so its span is `described` (the eleventh), and a string
search is the wrong instrument for a picture. `described` says the evidence was
not checkable by search. It says nothing about whether the value is right. The
verified answer caught it: `2026-09-02` is `PLAY-3001`'s incident, the week's
worst hour, and not the day this review was resolved.

With page 2 abstaining instead:

```console
$ rm -rf .dossier/cache/stage/ && dossier run observability-audit
  extract: 6 document(s) · 0 from cache · 0 failed · 10 described · tokens not reported
$ dossier eval observability-audit --gold gold/observability
6 documents · 5 fields · overall 100.0%
  incident_date      100.0%
  ...
```

Page 1 answered, and an abstention is not an answer for its document while
another page gives one (R7.47). Scored per record, as before 2026-09-28, that
abstention was a miss against `2026-09-08`, and the field read 85.7% again.

With page 1's rule overridden to drop the date, and page 2 back to its empty
answer:

```console
$ rm -rf .dossier/cache/stage/ && dossier run observability-audit
  extract: 6 document(s) · 0 from cache · 0 failed · 10 described · tokens not reported
$ dossier eval observability-audit --gold gold/observability
6 documents · 5 fields · overall 96.7%
  incident_date       83.3%   <- weakest
    PLAY-3005-weekly-incident-review.pdf not answered; gold states '2026-09-08'
  ...
```

Before R7.50 a field no record answered was not scored at all, so this run read
`incident_date 100.0%` over five documents. A run that left out what it was
unsure of was never wrong about it. Had page 2 still abstained, the line would
read `abstained on every page; gold states '2026-09-08'`: the same miss, told
apart from silence.

Each of the three runs is nine calls in the log, and a second eval adds none.

---

## What this exercise was really about

A chart used to be unreadable by construction. Not badly read — *unreadable*: the
only media type a stage could be shown was text, `page_images` was an artifact no
step could name, and a figure drawn on a panel was invisible to every rule in
`specs/`. The three pieces here are what changed that, and each one is a rule you
can go and read:

- a picture is an artifact — one container of parts, because parts of a document
  are not documents (R8.11, R8.12);
- a page is a call — keyed, retried, cached and replayed on its own (R3.12,
  R4.14);
- a description is a third state — neither a pass nor a failure, judged by a
  judge shown the pages and gated on a bar measured for exactly that (R6.15,
  R7.20–R7.24).
