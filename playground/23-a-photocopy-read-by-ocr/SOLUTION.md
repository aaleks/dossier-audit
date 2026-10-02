# 23 · Solution

Every command below was run against this repository, in order and in one pass,
on 2026-10-02, against the stub. Docling 2.130.0 ran on a CPU with the pinned
weights. The output shown is the output it produced. The workspace's absolute
path is cut from the `run` lines and from the paths Docling names, and the run
ids and timings are that pass's. Yours will differ.

## Run the prepared answer

After the setup in `README.md`, terminal 1:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/23-a-photocopy-read-by-ocr/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Terminal 2:

```bash
E=playground/23-a-photocopy-read-by-ocr
.venv/bin/python playground/toolkit/make_photocopies.py --out playground/work/23/inbox/scans
cp -r $E/solution/workspace/. playground/work/23/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/23/.env

cd playground/work/23
D=../../../.venv/bin/dossier
$D sync weekly-review && $D convert weekly-review && $D run weekly-review
```

The prepared `sources.yaml` already names `docling-markdown`. That is where
task 3 ends up.

---

## Task 1 — two scans, and the converter that reads text

```console
$ python playground/toolkit/make_photocopies.py --out playground/work/23/inbox/scans
playground/work/23/inbox/scans/PLAY-3007-weekly-review-photocopied.pdf  461180 bytes
playground/work/23/inbox/scans/PLAY-3008-weekly-review-half-photocopied.pdf  340123 bytes
```

Run twice, it writes the same bytes. PDFium draws with its own fonts, not the
machine's (R8.28), so the snapshots below hash the same on your machine.

```yaml
# sources.yaml, for now
sources:
  - id: scans
    type: folder
    path: inbox/scans/
```

```yaml
# pipelines/weekly-review/schemas/review.yaml
fields:
  resolution_date:  {kind: date}
  severity:         {kind: enum, values: [minor, major, critical]}
  affected_systems: {kind: reference}
  root_cause:       {kind: free_text, judge: rubrics/root_cause.md}
```

```console
$ dossier sync weekly-review
scans  0 known · 0 changed · 2 new -> 2 fetched
ledger updated · 2 new snapshots · 0 tombstoned

$ dossier convert weekly-review
scans  2 held · 2 converted · 0 cached
cache updated · 2 converted · 0 cached

$ python ../../03-html-exports-and-a-converter-you-write/resources/artifacts.py --cat
PLAY-3007-weekly-review-photocopied.pdf   snapshot 98372200  pdf-markdown        1.1.0     66 bytes  sha256 67e1a6767403
  .dossier/cache/convert/28/b1/28b199ad7df22b81c00066b86dab4a21d173d651c80dd5cf55e00ebc5f7f405c
    <!-- page 1 -->

    <!-- page 2 -->

    <!-- page 3 -->

    <!-- page 4 -->

PLAY-3008-weekly-review-half-photocopied.pdf snapshot e01534fd  pdf-markdown        1.1.0    617 bytes  sha256 f175c21c54c5
  .dossier/cache/convert/59/90/5990d2635b5de428c57eb3c1367a197912860b9822a3d6e2b30ce6acc22fb914
    <!-- page 1 -->
    PLAY-3005 -- Weekly incident review
    Document key: PLAY-3005-weekly-incident-review.pdf | page 1 of 4
    Severity: critical
    Resolved: 2026-09-08
    Affected systems: checkout-service, payments-api, edge-gateway
    Root cause: the three incidents of the week share one cause -- a retry
    budget that is configured per service and enforced nowhere, so each
    component amplified the failure of the one beneath it.
    The three panels that follow are the evidence the review was held over. The
    revenue at risk for the week is on the last of them and in no sentence here.

    <!-- page 2 -->

    <!-- page 3 -->

    <!-- page 4 -->
```

- **The key** is the file's name, which is what a `folder` source keys an item
  by. The words on the page are content. A photocopy of `PLAY-3005` still says
  `PLAY-3005`, as a photocopy of a letter still carries the letter's date.
- **Not a failure.** `pdf-markdown` read the text layer, and the photocopy's is
  empty. Four page markers is a faithful account of what that converter can see
  (R8.1). If it failed, a reader would think the file was broken. The file is
  fine; it is a picture.

## Task 2 — a model shown nothing

```console
$ dossier run weekly-review
run 20261002T063425Z-ba38 · runs/20261002T063425Z-ba38/manifest.json
  extract: 2 document(s) · 0 from cache · 0 failed · tokens not reported
```

```
PLAY-3007-weekly-review-photocopied.pdf
resolution_date   None        | The review holds no text: four page markers and nothing between them.
severity          None        | The review holds no text: four page markers and nothing between them.
affected_systems  None        | The review holds no text: four page markers and nothing between them.
root_cause        None        | The review holds no text: four page markers and nothing between them.

PLAY-3008-weekly-review-half-photocopied.pdf
resolution_date   2026-09-08  | Resolved: 2026-09-08
severity          critical    | Severity: critical
affected_systems  checkout-service, payments-api, edge-gateway | Affected systems: checkout-service, payments-api, edge-gateway
root_cause        the three incidents of the week share one cause -- ... | Root cause: the three incidents of the week share one cause -- a retry budget ...
```

The root cause's span runs across three lines of `PLAY-3008`'s page and is
still found. Whitespace is folded before a span is searched (R6.4).

- **Nothing is wrong, and nothing is right.** The model abstained, with a
  reason, which is an answer (R6.5). Against a gold set it scores correct only
  where gold says the value is not there (R7.3), and gold says it is. So
  `dossier eval` would name `PLAY-3007` under every field with that reason.
  The run itself cannot know that the paper said more than the PDF does.
- **Exercise 10's way** sends each page to the model as a picture: a
  `per_part` step, one call per page. Values read off the picture are
  `described`, and a judge shown the pages decides them (R6.15). It works on a
  chart, which OCR cannot read. It costs a vision call per page on every run,
  where OCR is paid once, at conversion, and cached.

## Task 3 — weights it will not fetch

```yaml
# sources.yaml
converters: [docling-markdown]
```

```console
$ mkdir no-models
$ DOCLING_CACHE_DIR=$PWD/no-models dossier convert weekly-review
scans  2 held · 0 converted · 0 cached · 2 failed
    PLAY-3007-weekly-review-photocopied.pdf: ValueError: docling-markdown reads docling-project/docling-layout-heron at commit 8f39ad3c, and no-models/models/docling-project--docling-layout-heron/config.json is not there. Nothing is downloaded while converting; fetch it once with:
  hf download docling-project/docling-layout-heron --revision 8f39ad3c0b4c58e9c2d2c84a38465abf757272d8 --local-dir no-models/models/docling-project--docling-layout-heron
    PLAY-3008-weekly-review-half-photocopied.pdf: ValueError: docling-markdown reads docling-project/docling-layout-heron at commit 8f39ad3c, and no-models/models/docling-project--docling-layout-heron/config.json is not there. Nothing is downloaded while converting; fetch it once with:
  hf download docling-project/docling-layout-heron --revision 8f39ad3c0b4c58e9c2d2c84a38465abf757272d8 --local-dir no-models/models/docling-project--docling-layout-heron
cache updated · 0 converted · 0 cached
$ echo $?
1
$ ls -A no-models
$
```

- **Never fetched.** Conversion is right of the hash boundary (R0.19). An
  artifact must be a function of the snapshot and the converter's version, and
  nothing else (R8.1). A model pulled from the Hub on first use is whatever
  `main` pointed at that day. Two machines would then write two artifacts under
  one key, and a key that lies is worse than none. So the weights are read
  from disk at a pinned commit, and a missing one is named with the command
  that fetches it (R8.15).
- **Each document fails** because a conversion failure belongs to its document
  (R8.6). The same message twice is the honest report: each document was tried,
  and each needed the file.

## Task 4 — the pictures read back

```console
$ time dossier convert weekly-review
scans  2 held · 2 converted · 0 cached
cache updated · 2 converted · 0 cached

real	0m36.784s
```

That was a second pass on a machine where Docling had already loaded once. The
very first conversion took 2 minutes 15 seconds.

```console
$ python ../../03-html-exports-and-a-converter-you-write/resources/artifacts.py --cat
PLAY-3007-weekly-review-photocopied.pdf   snapshot 98372200  docling-markdown    1.1.0   1018 bytes  sha256 656ce4de7f42
  .dossier/cache/convert/b1/ed/b1edd7f1ce2e23960d0547624f1ddc1fa451a955f6fd5e01b7255e62ec97fabf
    <!-- page 1 -->
    PLAY-3005-- Weekly incident review Document key: PLAY-3005-weekly-incident-review.pdf | page 1 of 4

    Severity:critical Resolved:2026-09-08 Affected systems: checkout-service, payments-api, edge-gateway

    Root cause: the three incidents of the week share one cause -- a retry budget that is configured per service and enforced nowhere, so each component amplified the failure of the one beneath it.

    The three panels that follow are the evidence the review was held over. The revenue at risk for the week is on the last of them and in no sentence here.

    <!-- page 2 -->
    ## PLAY-3005 -- Weekly incident review -- latency Document key: PLAY-3005-weekly-incident-review.pdf| page 2 of 4

    Checkout latency across the week, by percentile.

    <!-- page 3 -->
    Document key: PLAY-3005-weekly-incident-review.pdf| page 3 of 4

    Heap behaviour on payments-api during the same week.

    <!-- page 4 -->
    Document key: PLAY-3005-weekly-incident-review.pdf | page 4 of 4

    Errors logged across the week, and the cost of them.

PLAY-3007-weekly-review-photocopied.pdf   snapshot 98372200  pdf-markdown        1.1.0     66 bytes  sha256 67e1a6767403
  ...

PLAY-3008-weekly-review-half-photocopied.pdf snapshot e01534fd  docling-markdown    1.1.0   1024 bytes  sha256 5100e675374f
  .dossier/cache/convert/98/c5/98c54e254fd5d8102644379f80a5f574acf7f160121519eaa53abf14fe73662b
    <!-- page 1 -->
    PLAY-3005 -- Weekly incident review

    Document key: PLAY-3005-weekly-incident-review.pdf | page 1 of 4

    Severity: critical

    Resolved: 2026-09-08

    Affected systems: checkout-service, payments-api, edge-gateway

    Root cause: the three incidents of the week share one cause -- a retry budget that is configured per service and enforced nowhere, so each component amplified the failure of the one beneath it.

    The three panels that follow are the evidence the review was held over. The revenue at risk for the week is on the last of them and in no sentence here.

    <!-- page 2 -->
    (pages 2 to 4 as in PLAY-3007)

PLAY-3008-weekly-review-half-photocopied.pdf snapshot e01534fd  pdf-markdown        1.1.0    617 bytes  sha256 f175c21c54c5
  ...
```

- **Both conversions are kept** because a conversion's key holds the converter's
  id and version (R5.4, R8.2). Naming another converter is another key, not an
  overwrite. Take `converters:` out again, and the next run is served
  `pdf-markdown`'s artifacts from cache without converting anything.
- **Page by page.** `PLAY-3008`'s page 1 has a text layer, and that layer is
  exact. OCR could only make it worse, so Docling reads the layer there and
  OCRs only the pages that have none (R8.14). One decision for the whole
  document would OCR good text or skip pictures. A document printed half,
  scanned and merged is exactly the case of a document that is both.
- **What OCR changed.** It dropped the space after each colon
  (`Severity:critical`) and after `PLAY-3005`. It also ran the title into the
  key line, and the next three lines into one. Spec 008 records the same behaviour of Docling's
  OCR. The money figure on page 4's panel is not in the text: it is drawn small,
  inside a chart, and OCR read the caption and not the chart. A figure that
  matters on a scan is a figure to check, which is what exercise 10's
  `described` state is for.

## Task 5 — grounded again

```console
$ dossier run weekly-review
run 20261002T063504Z-c282 · runs/20261002T063504Z-c282/manifest.json
  extract: 2 document(s) · 0 from cache · 0 failed · tokens not reported
```

```
PLAY-3007-weekly-review-photocopied.pdf
resolution_date   2026-09-08  | Resolved:2026-09-08
severity          critical    | Severity:critical
affected_systems  checkout-service, payments-api, edge-gateway | Affected systems: checkout-service, payments-api, edge-gateway
root_cause        the three incidents of the week share one cause -- ... | Root cause: the three incidents of the week share one cause -- a retry budget ...

PLAY-3008-weekly-review-half-photocopied.pdf
(as in task 2)
```

The manifest's `converters`:

```
{'id': 'docling-markdown', 'version': '1.1.0', 'media_type': 'application/pdf', 'kind': 'markdown'}
```

- **`PLAY-3008` was asked again** because its text is not the same bytes:
  Docling writes paragraphs where `pdf-markdown` wrote lines. A step's key
  holds the hash of the text it reads (R5.2), not the words a person would
  say it holds.
- **The version** names Docling's layout and table code, RapidOCR and the OCR
  models inside its wheel, the runtime that executes them, and the weights at
  their commits. `pyproject.toml` pins the `docling` extra exactly for that
  reason: a new release of any of them can change an artifact under a key
  claiming nothing did. Moving a pin means raising the converter's version
  (R8.2).

## Task 6 — a model that tidies what it quotes

Terminal 1:

```bash
E=playground/23-a-photocopy-read-by-ocr/resources
.venv/bin/python playground/toolkit/stub_model.py \
  --replies $E/replies-published-wording.json --replies $E/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

```console
$ rm -rf .dossier/cache/stage && dossier run weekly-review
run 20261002T063509Z-62aa · runs/20261002T063509Z-62aa/manifest.json
  extract: 2 document(s) · 0 from cache · 0 failed · 2 finding(s) · tokens not reported
    PLAY-3007-weekly-review-photocopied.pdf  resolution_date: span not found in PLAY-3007-weekly-review-photocopied.pdf (R6.4).
    PLAY-3007-weekly-review-photocopied.pdf  severity: span not found in PLAY-3007-weekly-review-photocopied.pdf (R6.4).
```

- **Not grounded**, because grounding searches the document `dossier` holds,
  and that is the OCR'd text. `Severity: critical` is not in it. The paper is
  not something any step can search.
- **No folding adds a space.** The folds undo differences that mean nothing:
  a ligature, a typographer's quote, a word broken at a line end, two spaces
  where one would do (R6.17 – R6.19). Each one maps both sides to one form.
  Ignoring spaces altogether would make `2026-09-08` match `20 26-09-08`, and
  `pay ments-api` match `payments-api`. It would also let a span stitched from
  two neighbouring words "ground" a word that is not there. A missing space is
  a real difference in the text, so it is reported.
- **The prompt** says "quoted as the document writes it". A real model shown
  OCR text will sometimes tidy it anyway. On scanned corpora, compare the span
  `run` names with the artifact (task 4's helper). If the span reads as the
  paper reads and the artifact does not, the model tidied it. Then tighten the
  prompt, or let a judge decide those fields.

## Task 7 — a name nothing answers

```console
$ dossier convert weekly-review          # converters: [docling-markdwn]
sources.yaml names docling-markdwn under converters:, and no installed package provides it. Installed: confluence-page-markdown, docling-markdown, html-markdown, jira-issue-markdown, jpeg-pages, markdown-text, pdf-images, pdf-markdown, png-pages, text-csv, text-plain. A converter is added by installing a package that declares a dossier.converters entry point.
$ echo $?
2
```

- **Ignored**, it would be silently no choice at all. `pdf-markdown` would
  answer, the photocopy would convert to four page markers, and the run would
  report nothing wrong, exactly as in task 2. A name that answers nothing is
  refused before anything is converted (R8.13 row 4).
