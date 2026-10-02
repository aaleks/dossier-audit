# 23 · A photocopy, read by OCR

**You will build:** an audit of a weekly incident review that reached you as a
photocopy, every page a picture, beside the same review with only its first
page photocopied. You will read both first with the converter `dossier` uses
by default, and then with Docling, which reads a picture of a page back into
text.

**You will learn:** what a photocopy lacks that a born-digital PDF has; how a
workspace names the converter that answers a PDF; why Docling never fetches a
model while it converts, and what it says when one is missing; which pages it
reads by OCR and which from their text layer; how an OCR'd page can differ
from the page it was photographed from; and why a quoted span must be what
the converted document says, not what the paper said.

**Needs Docling.** That means the `docling` extra, which brings torch and
weighs gigabytes, and Docling's model weights at the commits `dossier` pins.
After that it runs offline. The first conversion of the two scans takes
between half a minute and a few minutes on a CPU, and is cached after that.
The model is the stub.

---

## Background, in one paragraph

A born-digital PDF is two things at once: a picture of each page, and a text
layer behind it that says which characters are where. `pdf-markdown` reads
the text layer, and nothing else. A photocopy has no text layer: every page is
a picture of a page. Exercise 10 answered that with the pictures themselves.
The pages went to the model, and a value read off them was `described`,
neither grounded nor failed, for a judge to decide. OCR is the other answer.
It reads the picture back into text, so that a value can be grounded again,
on the page it is printed on (R8.14). The price is that OCR writes down what
it sees. That is close to what was typed, and it is not always the same.

---

## Setup

```bash
uv sync --all-extras                # the docling extra, and pypdf from the dev group
hf download docling-project/docling-layout-heron --revision 8f39ad3c0b4c58e9c2d2c84a38465abf757272d8 \
  --local-dir ~/.cache/docling/models/docling-project--docling-layout-heron
hf download docling-project/docling-models --revision fc0f2d45e2218ea24bce5045f58a389aed16dc23 \
  --include "model_artifacts/tableformer/accurate/*" \
  --local-dir ~/.cache/docling/models/docling-project--docling-models
```

The two `hf download` lines are `README.md`'s, under "Installing". You need
them once per machine.

Terminal 1, the stub:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/23-a-photocopy-read-by-ocr/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

## Task 1 — two scans, and the converter that reads text

Make the scans. They are photocopies of exercise 10's `PLAY-3005`, made on
demand:

```bash
.venv/bin/python playground/toolkit/make_photocopies.py --out playground/work/23/inbox/scans
```

```
PLAY-3007-weekly-review-photocopied.pdf        every page a picture
PLAY-3008-weekly-review-half-photocopied.pdf   page 1 as published, pages 2-4 pictures
```

Make the workspace under `playground/work/23/`:

- `sources.yaml` holds one `folder` source, `scans`, over `inbox/scans/`.
  Leave `converters:` out for now.
- `pipelines/weekly-review/` holds one `per_file` step, `extract`, over
  `documents`, with these four fields:
  - `resolution_date` (`date`);
  - `severity` (`enum`: minor, major, critical);
  - `affected_systems` (`reference`);
  - `root_cause` (`free_text`, with exercise 10's rubric as its `judge:`).

  The prompt asks for each value with the exact sentence it came from, "quoted
  as the document writes it".
- Copy the `.env` from exercise 02.

Sync, convert, and print what was converted with exercise 03's helper:

```bash
python ../../03-html-exports-and-a-converter-you-write/resources/artifacts.py --cat
```

**Checkpoint.** Both convert, and neither fails:

- `PLAY-3007` is four page markers with nothing between them, 66 bytes.
- `PLAY-3008` has its first page's text and nothing on pages 2 to 4.

Questions:

- The photocopy's pages still say `PLAY-3005`. Where does the document's key
  come from, then?
- `PLAY-3007` converted "successfully" to nothing. Why is that not a conversion
  failure? What, exactly, did `pdf-markdown` read? (R8.1.)

## Task 2 — a model shown nothing

Run the pipeline, then open both answers under `runs/<id>/extract/`.

**Checkpoint.**

- `extract: 2 document(s) · 0 from cache · 0 failed`.
- `PLAY-3007` answers every field `null`, with the reason "The review holds no
  text: four page markers and nothing between them."
- `PLAY-3008`'s four values are grounded on page 1.

Questions:

- The run reports nothing wrong. Is that right? What is a reviewer told about
  `PLAY-3007`, and where? (R6.5, R7.3.)
- What would exercise 10's way have given here instead, with `page_images` and
  a `per_part` step? What would it have cost per page?

## Task 3 — weights it will not fetch

Add `converters: [docling-markdown]` to `sources.yaml`. Then, **before**
converting for real, point Docling at an empty folder:

```bash
mkdir no-models
DOCLING_CACHE_DIR=$PWD/no-models dossier convert weekly-review
ls -A no-models
```

**Checkpoint.**

- Each document fails on its own, naming the file that is not there and the
  `hf download` line that fetches it.
- `convert` exits 1.
- `no-models` is still empty: nothing was downloaded.

Questions:

- Docling's own default is to download a missing model on first use. Why does
  `dossier` refuse to? What would a conversion made with "whatever the Hub
  served that day" do to a key? (R8.15, R8.2.)
- Why does each document fail, and not the command? (R8.6.)

Delete `no-models`.

## Task 4 — the pictures read back

Convert again, without the variable, and time it. Then print the artifacts.

**Checkpoint.** There are four artifacts now, two per document, one from each
converter.

- In `PLAY-3008`, Docling read page 1 from its text layer: the same words as
  `pdf-markdown`'s, in paragraphs.
- In `PLAY-3007`, page 1 was read by OCR, and it begins:

  ```
  Severity:critical Resolved:2026-09-08 Affected systems: checkout-service, ...
  ```

- Pages 2 to 4 hold their captions, read by OCR in both documents.

Questions:

- Why are the `pdf-markdown` artifacts still there, beside Docling's? What is
  in a conversion's key? (R5.4.)
- Docling read `PLAY-3008`'s first page from its text layer, and its other
  three by OCR. Why decide page by page rather than once per document? (R8.14.)
- What did OCR change on `PLAY-3007`'s page 1? The panels' money figure is
  drawn small, inside a chart. Did OCR find it? What does that tell you about
  trusting OCR with a figure?

## Task 5 — grounded again

Run the pipeline. Open both answers, and the manifest's `converters`.

**Checkpoint.**

- `extract: 2 document(s) · 0 from cache · 0 failed`, with no findings.
- `PLAY-3007` is answered now, with spans as OCR wrote them: `Severity:critical`.
- The manifest pins `docling-markdown` `1.1.0` for `(application/pdf, markdown)`.

Questions:

- `PLAY-3008` was asked again, though its first page says the same words. Why?
- What does `docling-markdown`'s version name, besides `dossier`'s own code?
  Why can a new release of Docling not be picked up quietly? (R8.2, and the
  comment on the `docling` extra in `pyproject.toml`.)

## Task 6 — a model that tidies what it quotes

Restart the stub with `resources/replies-published-wording.json` in front of
`replies.json`. In it, the photocopy is answered as the paper reads, with a
space after each colon: `Severity: critical`. Delete `.dossier/cache/stage/`
and run.

**Checkpoint.**

```
  extract: 2 document(s) · 0 from cache · 0 failed · 2 finding(s) · tokens not reported
    PLAY-3007-weekly-review-photocopied.pdf  resolution_date: span not found in PLAY-3007-weekly-review-photocopied.pdf (R6.4).
    PLAY-3007-weekly-review-photocopied.pdf  severity: span not found in PLAY-3007-weekly-review-photocopied.pdf (R6.4).
```

Questions:

- `Severity: critical` is what the paper says. Why is it not grounded?
- A span is compared after folding: NFKC, quotes and dashes, words broken by a
  hyphen, runs of whitespace (R6.17 – R6.19). Why does none of them add a
  space that is missing? What could go wrong if one did?
- Which sentence in the prompt asks the model not to do this? What would you
  check first if a real model's spans on scanned documents kept failing?

## Task 7 — a name nothing answers

Misspell the converter: `converters: [docling-markdwn]`, and convert. Then
spell it right again.

**Checkpoint.** Refused before anything is converted, with exit 2, naming
every installed converter (R8.13 row 4).

- What would a misspelt name have done if it were ignored instead?

---

## Done when

- you can say what a text layer is, and which converter reads what when a PDF
  has one, half of one, or none;
- you can make a workspace name the converter that answers a pair, and say
  what that does to every key it touches;
- you can say why Docling's weights are pinned and never fetched, and what a
  missing one costs;
- you can read an OCR'd page against the page it was photographed from, and
  say why a span must quote the first.

**Back to:** [the playground index](../README.md).
