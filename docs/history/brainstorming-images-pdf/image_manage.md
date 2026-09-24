# Images in dossier — notes toward a decision

Written 2026-09-18, during playground exercise 03. Nothing here is implemented
or agreed; it is the discussion, kept so the decision can be made later.

## Where things stand today

- `page_images` is a real kind. Exercise 03 Task 4 registers
  `(application/pdf, page_images)`, and the artifact is a real cache entry:
  counted by `convert`, keyed by `K_convert`, invalidated by a version bump.
- **No stage is ever shown it.** `ConvertReport.text`
  (`src/dossier/application/convert.py:116-119`) hands a stage only the
  `markdown` kind. The solution says this outright
  (`playground/03-.../SOLUTION.md:201-210`): "a pipeline that wants to *reason*
  over them needs a step whose input is that artifact, which is a spec
  conversation nobody has had yet."
- This is consistent with the rest of the specs, not an oversight in one
  function:
  - `ModelClient.complete(prompt: str, ...)` (`src/dossier/domain/ports.py:100`)
    is text-only. There is no port through which bytes reach a model.
  - R6.4 grounds a span by string search in converted text. A span has nothing
    to be located in if the evidence is an image.
  - R8.1: a converter is a pure function of bytes and options — no clock, no
    network, no model.
  - R0.10: only `infrastructure.models` may reach a model. A converter is left
    of the hash boundary.
- `image/png` is not in `MEDIA_TYPES` at all; exercise 04 covers what happens
  with an unrecognised media type and asks what the default kind for an image
  should be.

## Why `page_images` exists anyway

The exercise uses it to make the mechanism visible on one snapshot:

- registration is by the **pair** `(media type, kind)`, not the media type (R8.4);
- a version bump invalidates exactly that converter's artifacts and nobody
  else's (R5.4) — only observable with two converters on the same document;
- an unclaimed pair stops the run even when the media type is claimed for
  another kind (R8.6 row 3).

## The concern

A `loss_amount` that exists only inside a scanned table, or a chart, is lost
information today. `PLAY-2002-photocopy-no-text-layer.pdf` shows it: the
markdown artifact is 17 bytes. `dossier convert` makes this visible *before*
model calls are spent, but that is all it does — the field comes back null or
ungrounded and the images that hold the answer sit unread in the cache.

Cases wanted in the long run:

1. PDFs with images inside (charts, graphs, screenshots);
2. a postmortem delivered as one huge PNG — text + charts in one image.

## OCR vs vision model

Classical OCR (Tesseract, PaddleOCR, `ocrmypdf`) is character recognition. It
does not use a multimodal LLM and does not understand what it reads. That is
exactly why it fits R8.1 (deterministic given a pinned engine) and why it is not
enough on its own.

| Content in the image | Classical OCR | Vision LLM |
|---|---|---|
| Body text, headings | good | yes |
| Table | characters yes, structure often scrambled | can emit a markdown table |
| Bar/line chart | axis labels and legend words only; no values, no trend | can describe it — but that is an *interpretation*, not extraction |
| Diagram / screenshot with arrows | no | yes |
| Handwriting, poor scans | weak | better |

For a PNG postmortem with text + charts, OCR covers the text half and drops the
chart half. It fixes `PLAY-2002`; it does not make a chart's `loss_amount`
readable.

## What a vision model would break as the specs stand

1. **A model call during conversion.** A "vision converter" that calls a model
   violates R8.1 (purity) and R0.10 (hash boundary). It could be done — a
   converter reached through `ModelClient`, cached like a stage — but it is a
   spec amendment, and a converter whose output is a model's interpretation is
   not deterministic in the way R8.1 promises. A version bump on `pdf-markdown`
   means "the code changed"; on a vision converter it would mean "the model
   changed". Spec 009 handles that for stages via the pinned identifier; spec
   008 has no notion of it.
2. **Grounding.** If a vision model writes "the chart shows losses of
   CHF 48'200" and the extraction stage copies that span, it grounds — but in
   the model's *description* of the chart, not the document. Nobody can locate
   the span in the PNG by string search. The verifiable thing for a chart is a
   region of a page, and no spec defines that.

## Options

### Option 1 — richer text at conversion time (OCR converter)

An OCR converter for `(application/pdf, markdown)` and `(image/png, markdown)`.
Stays inside spec 008's shape: artifact is text, grounding works by string
search, deterministic given a pinned engine version. Small slice; possibly only
an example row in 008. Covers scans of text. Does **not** cover charts.

### Option 2 — a step that takes a non-text input (vision through a stage)

A step whose `input:` names a converted kind (`page_images`) and a `ModelClient`
method that accepts image parts. Touches spec 003/004 (what an input can be),
009 (the port), 006 (what "grounded" means when the evidence is a region, not a
substring). Multi-spec `/discover`.

### Proposed long-run shape (combines both; not decided)

- **Two layers of conversion.** OCR stays a plain converter under spec 008 as
  it is — deterministic, cheap, no spec change. Fixes the no-text-layer case.
- **A `describe` step kind, not a converter, for visual content.** A pipeline
  step whose input is the `page_images` artifact and whose output is text, run
  through `infrastructure.models`, cached by stage key, pinned model id,
  tracked in MLflow like any stage. Later steps read it as `previous`. Keeps
  R8.1 and R0.10 intact and reuses what spec 004/005/009/011 already do for a
  model call. Spec cost: an input may name a converted *kind*, and
  `ModelClient` grows an image-carrying method.
- **Grounding distinguishes "grounded in the document" from "grounded in a
  description".** A span found in a `describe` step's output is
  provenance-traceable (which page image the model saw) but not
  string-verifiable. Spec 006 needs a third state, or a flag on the field, so
  the scorer and the human reading the report know the difference. Must not be
  invented silently.
- **Where the PNG lands.** With this shape the exercise 04 question answers
  itself: the default kind for an image is `page_images`, and a `markdown` kind
  exists only if an OCR converter claims it. The standalone PNG and the image
  inside a PDF end up on the same path.

## Before opening a spec

A real gold case where the answer lives only in a chart, so spec 007's
threshold has something honest to measure. `PLAY-2002` is the only visual
fixture and its content is text. Add the fixture to `specs/_fixtures.md`, not a
new incident key invented ad hoc.

## Open questions

- Is OCR alone worth landing first as its own slice, before the `describe`
  conversation? (My recommendation at the time: yes — small, no spec change,
  fixes a real case; but it does not address the chart case that motivated
  this.)
- Should the `describe` output be a first-class kind (`page_descriptions`)
  rather than a step, so that a version/model change invalidates it via
  R5.4-style rules? Or is a stage key already the right invalidation?
- What does the report show a human for a field grounded in a description —
  the page image, the description, both?
- Does a `describe` step count against the judge's calibration (spec 007) —
  is "supported by the document" still the right question when the document
  the judge sees is a description?
