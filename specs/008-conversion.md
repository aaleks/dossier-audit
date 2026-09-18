# 008 — Conversion

**Status:** Partially implemented
**Rules:** R8.1 – R8.11

## Purpose

A snapshot is bytes as a source gave them. A stage reads text. Conversion is the
step between, and it is the first thing right of the hash boundary: from here on
everything is a pure function of content that is already frozen.

That position is the whole design constraint. `K_convert` claims an artifact is
determined by four things — the snapshot hash, the converter id, its version and
its options (spec 005). If a converter consults anything else, the key is a lie:
the cache serves text that no longer matches what the converter would produce
today, nothing detects it, and every stage above inherits the error with a
provenance record that looks correct.

This spec was written because R5.4 already governs what happens when a converter
version changes, and spec 004 requires a run manifest to record converter
versions, while nothing defined what a converter *is*, what its version means,
or which converter handles which snapshot. Spec 001 does exactly that job for
connectors; this is its counterpart.

## The interface

A converter answers one question: given these bytes and these options, what is
the artifact? It is registered against the pair it claims.

```
snapshot                    sources.yaml
  media_type                  convert: [markdown, page_images]
  application/pdf                    │
        └──────────────┬─────────────┘
                       ▼
       (application/pdf, markdown)     ──▶  pdf-markdown  1.3.0
       (application/pdf, page_images)  ──▶  pdf-images    0.9.1
```

The pair is `(media type, kind)`. Media type comes from the snapshot, which
already carries it (`RawItem.media_type`, spec 001). Kind comes from the source's
`convert:` list, or is the default for that media type when the source declares
none. Neither half alone is enough: media type cannot express that one PDF is
wanted as text and another as page images, and a declared kind cannot say what
the bytes actually are.

Registration is by entry point in the `dossier.converters` group, exactly as
connectors use `dossier.connectors` (R1.7). A converter is a package, never a
branch in a `match` statement inside `dossier`.

## Versioning

A converter declares an `id` and a `version`. The id names the thing; the version
names its behaviour. Both enter every convert key and every provenance record, so
raising a version invalidates every artifact that converter produced and nothing
else (R5.4).

The obligation on a converter's author is therefore precise, and it is worth
stating even though no test can enforce it: **raise the version whenever output
could change for the same input.** A converter that improves its table extraction
without raising its version leaves a cache full of artifacts that claim to be
something they are not, and there is no mechanism anywhere that will notice.

## Two kinds of failure

They look similar and behave differently, on purpose.

| What happened | Blast radius | Because |
|---|---|---|
| no converter claims a media type | the whole run stops | the pipeline is not configured to read what it was pointed at. Nothing about the run is well-defined, and the fix is an installation, not a retry |
| a converter fails on one document | that document only | the configuration is right and one input is bad. An audit over nine of ten documents is useful, provided it says which one is missing |

The first is `UnknownSourceType`'s shape (spec 001), reported before any work
starts. The second is R6.9's shape, reported per document with a non-zero exit.

## The command

`dossier convert <pipeline>` converts what the pipeline needs and reports what it
did. It is optional: `run` converts what it needs anyway, and conversion is
idempotent and cached, so running it early costs nothing. It exists so that the
text a stage will actually see can be inspected before a single model call is
made — which for a PDF-heavy corpus is usually where the surprises are.

## Where a converted artifact lives

`.dossier/cache/`, keyed by `K_convert`. This is not a preference: R5.9 says the
cache is an optimisation and never a source of truth, and R5.4 says raising a
converter version makes every document re-convert — which only means anything if
conversions are otherwise reused *across runs*. An artifact stored under
`runs/<run_id>/` would be a run output rather than a cache entry, every run would
re-convert, and R5.4 would have nothing to act on.

Spec 005's provenance example showing `converted/INC-4821.md` does not contradict
this. The paths in a provenance record are relative to their own root, not to the
workspace: `prompts/02_verify.md` in that same record resolves against the
pipeline's directory, because a pipeline is self-contained and can be moved.
`converted/INC-4821.md` is the artifact's *name*; spec 000's layout says where its
bytes are kept. Those are different questions and the two specs each answer one.

Whether a run also materialises readable copies under `runs/<run_id>/converted/`
is deliberately not decided here. No rule needs it yet; it arrives with reporting
(spec 007) or with a command for reading an artifact back, and the sensible
answer depends on a corpus size nobody has measured.

## Must hold

### R8.1 — a converted artifact is a pure function of the snapshot bytes and the declared options

A converter reads the bytes it is given and its own options, and nothing else. No
clock, no locale, no environment variable, no file outside its input, no network
(R0.10).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters`)
- **Proved by:** `tests/unit/test_R008_1__conversion_is_a_pure_function_of_its_input.py`, `tests/unit/test_R008_1__a_pdf_converts_to_the_text_of_its_pages.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `audit-note.pdf` at `c4a70b93` converted twice by `pdf-markdown` `1.3.0` | byte-identical artifacts, and one cache entry |
| 2 | the same, in two processes with different `PYTHONHASHSEED` and working directories | byte-identical; nothing about the machine reaches the output (R0.4, R5.6) |
| 3 | a converter reading `datetime.now()`, a locale, or a font file outside its input | violation; the artifact is not reproducible and `K_convert` no longer describes it |
| 4 | *counter-example* — the same snapshot converted with `options: {ocr: true}` | a different artifact, legitimately; options are part of the key, so this is a different conversion rather than a different answer to the same one |

### R8.2 — a converter declares an id and a version, and both appear in every convert key and every manifest

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`, `dossier.domain.conversion`)
- **Proved by:** `tests/unit/test_R008_2__converter_identity_reaches_the_key_and_the_manifest.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `OPS-114` converted by `pdf-markdown` `1.3.0` | the convert key covers `b81f0c6d`, `pdf-markdown` and `1.3.0`; the provenance record names all three |
| 2 | a run over `incident-audit`, its manifest read afterwards | every converter used is listed with its version, so the run is reproducible without the installed packages (spec 004) |
| 3 | `pdf-markdown` raised `1.3.0` → `1.4.0` | every convert key it produced changes (R5.4) |
| 4 | *counter-example* — a converter that declares an id but no version | rejected at registration; a converter with no version cannot be invalidated, and R5.4 has nothing to act on |

### R8.3 — a converter is selected by the pair `(media type, kind)`, never by file extension

Media type comes from the snapshot; kind comes from the source's `convert:` list,
or is that media type's default when the source declares none.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.conversion.select`)
- **Proved by:** `tests/unit/test_R008_3__converter_is_selected_by_media_type_and_kind.py`, `tests/unit/test_R008_3__a_plain_text_document_converts_as_text.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `OPS-114`, `application/pdf`, source declares `convert: [markdown]` | `pdf-markdown` `1.3.0` |
| 2 | the same source declaring `convert: [markdown, page_images]` | both `pdf-markdown` and `pdf-images` are selected, for two artifacts (R8.4) |
| 3 | `audit-note.pdf` from a source declaring no `convert:` | the default kind for `application/pdf`, which is `markdown` |
| 4 | *counter-example* — a file named `notes.pdf` whose bytes are `text/markdown` | `markdown-text` is selected; the media type on the snapshot decides, and the name on disk is not evidence about content |

### R8.4 — one snapshot yields one artifact per declared conversion, each independently addressed and keyed

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R008_4__each_declared_conversion_is_its_own_artifact.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `OPS-114` with `convert: [markdown, page_images]` | two artifacts and two distinct convert keys, from one snapshot at `b81f0c6d` |
| 2 | `pdf-images` `0.9.1` → `0.9.2`, `pdf-markdown` untouched | the page-images artifact re-converts; the markdown artifact is served from cache |
| 3 | two snapshots with byte-identical content, same converter and options | one artifact; content addressing deduplicates, as it does for snapshots (R0.2 example 3) |
| 4 | *counter-example* — a stage declaring `input: documents` in a pipeline whose source produces two kinds | not resolved here; which kind a stage reads is a pipeline question (spec 003), not a conversion one |

### R8.5 — a media type no converter claims stops the run, naming the type and how to add one

Reported before any conversion starts. A pipeline pointed at bytes it cannot read
is misconfigured, and the fix is an installation rather than a retry.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.convert`)
- **Proved by:** `tests/unit/test_R008_5__an_unclaimed_media_type_is_a_configuration_error.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a snapshot of `application/zip` with no converter registered for it | the run stops; the error names the key, the media type, the claimed pairs available, and the `dossier.converters` entry point group |
| 2 | the same | no artifact is written and no stage runs; the failure is total, like a resolution failure (R4.1) |
| 3 | `application/pdf` registered for `markdown` only, a source declaring `convert: [page_images]` | the same error; the pair is unclaimed even though the media type is not |
| 4 | *counter-example* — a converter registered for the pair, which then fails on the bytes | not this rule; the configuration is right and one document is bad (R8.6) |

### R8.6 — a conversion failure is isolated to its own document

The other documents convert, the stages run over them, and the run says which
document failed and why.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.convert`)
- **Proved by:** `tests/unit/test_R008_6__a_conversion_failure_is_isolated.py`, `tests/acceptance/test_R008_6__a_run_reports_documents_that_failed_to_convert.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | ten documents, `INC-5044` truncated so `pdf-markdown` raises | nine artifacts written, `INC-5044` reported failed with its reason, exit code non-zero |
| 2 | the same | the nine are what the stages read; a partial audit is useful, a silent one is not (R6.9) |
| 3 | the same run repeated after `INC-5044` is repaired | the nine are served from cache and only `INC-5044` converts |
| 4 | *counter-example* — every document in the source failing to convert | still per-document rather than a single summary error; ten reasons are ten pieces of evidence, and collapsing them hides which failed how |

### R8.7 — adding a converter requires no edit to the `dossier` core package

A new converter is a package declaring a `dossier.converters` entry point. If
adding one means touching a file under `src/dossier/`, the interface has failed.

- **Kind:** deterministic
- **Layer:** architecture
- **Proved by:** `tests/architecture/test_R008_7__converters_are_resolved_only_by_entry_point.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `src/dossier/` scanned for converter ids and media types | no `match` or `if` dispatching on `"pdf-markdown"` or `"application/pdf"` outside the entry-point registry |
| 2 | a third-party package declaring `dossier.converters` entry point for `(application/vnd.ms-excel, markdown)` | an `.xls` source converts with no change to dossier |
| 3 | *counter-example* — `pdf-markdown` shipping in this package | allowed; it registers through the same group as any third party, with no special case (R1.7's shape) |

### R8.8 — `dossier convert` reports what it converted, per source and in total

The counts are the interface, as they are for sync (R2.13). A conversion that
says nothing is indistinguishable from one that was served entirely from cache.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.convert`)
- **Proved by:** `tests/acceptance/test_R008_8__convert_reports_counts_per_source.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-manual` holding three documents, none converted | `incidents-manual  3 held · 3 converted · 0 cached` |
| 2 | the same command run twice with nothing changed | the second reports `0 converted · 3 cached`, and writes nothing |
| 3 | `pdf-markdown` raised between the two runs | `3 converted · 0 cached`; the version is part of the key (R5.4) |
| 4 | *counter-example* — a source whose documents all failed | reported as failed with reasons and excluded from the converted count; a failure is not zero work (R8.6, R1.9's shape) |

### R8.9 — a manifest pins the converters the run used, and only those

R8.2 row 2 says every converter used is listed. The run pinned every converter
*installed* instead, and the difference is observable twice over. A manifest is
meant to be byte-identical across machines given the same inputs (R4.8), and
the packages a machine happens to carry are not an input the run read. And
`--plan` compares the pinned set to today's (R4.12 row 6), so installing or
uninstalling a plugin the corpus never needed printed `converters changed` on
every step reading documents -- a promise to re-ask that the run would not
keep, which is the one thing R4.12 forbids a plan to say.

"Used" is decided the way selection is (R8.3): a converter is used when it
claims the `(media type, kind)` pair of some document the run holds, under that
document's source's `convert:` list. Pinned in a stable order, so two machines
agree byte for byte.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.conversion.used`)
- **Proved by:** `tests/unit/test_R008_9__a_manifest_pins_only_the_converters_the_run_used.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-manual` holding markdown only, with `pdf-markdown` `1.3.0` installed beside `markdown-text` `1.0.0` | the manifest lists `markdown-text 1.0.0` alone |
| 2 | that run, then `pdf-markdown` uninstalled, then `dossier run --plan` | every step `cached`; nothing the run read moved (R4.12) |
| 3 | `OPS-114`, a PDF, held beside the markdown | `pdf-markdown 1.3.0` listed too; a converter is used when it claims a pair some held document has |
| 4 | *counter-example* — `pdf-markdown` raised to `1.4.0` with `OPS-114` still held | `converters changed` on every step reading `documents` (R4.12 row 6); a converter that *was* used is watched |
| 5 | *counter-example* — a run over a source holding nothing | pins no converters, and R4.12 row 10 reads that as nothing said, not as none |

### R8.10 — the default kind is read from a declared table, and a media type with no entry defaults to `markdown`

R8.3 says a source declaring no `convert:` gets "the default kind for that media
type" and leaves the table to be written. One constant answered for every media
type instead, which is right for text and wrong for the first media type that
has no text in it: a PNG resolved to `(image/png, markdown)`, so the pair a
person had to claim was the one an image cannot honestly supply.

The fallback stays `markdown` rather than becoming an error. A media type nobody
has agreed a default for is not a reason to stop — R8.5 already stops on the pair
that results, and it names a pair a reader can act on either way.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.conversion.default_kind`)
- **Proved by:** `tests/unit/test_R008_10__the_default_kind_is_read_from_a_declared_table.py`, `tests/acceptance/test_R008_10__an_image_source_asks_for_a_page_images_converter.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `audit-note.pdf`, `application/pdf`, its source declaring no `convert:` | `markdown`; the answer R8.3 row 3 already gives, unchanged |
| 2 | `INC-5720-checkout-latency-postmortem.png`, `image/png`, its source declaring no `convert:` | `page_images`; an image has no text layer, so the kind a stage reads is the one it cannot be given |
| 3 | `text/csv`, which the table has no entry for, its source declaring no `convert:` | `markdown`; a media type nobody has agreed a default for gets the one every text format already had, rather than no kind at all |
| 4 | that screenshot, with no converter installed for its pair | R8.5 stops the run naming `(image/png, page_images)` — the default decides *which* pair must be claimed, never whether one is |
| 5 | *counter-example* — that screenshot, from a source declaring `convert: [markdown]` | `markdown`; a declared kind wins and the table is not consulted at all (R8.3) |

### R8.11 — a conversion that produces several parts produces one artifact, a deterministic container

A page-images conversion of a forty-page PDF is forty pictures. R8.4 says one
declared conversion is one artifact with one key, and that is the right answer:
forty keys would let a version bump invalidate the pages of one document
separately, and no rule anywhere says what a document with nineteen old pages
and twenty-one new ones is.

So the parts travel together, in a container that is a pure function of its
contents. No timestamps, no compression that varies by library version, entries
in part order. R8.1 already requires the artifact to be byte-identical across
machines; this is what makes that achievable for an artifact that is not one
blob to begin with.

The container's format belongs to `domain` rather than to the converter that
writes it, for the reason the page anchor does (R6.14): a step will read what a
converter wrote, and a format written down twice is one that eventually differs.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.conversion.pack_parts`, `unpack_parts`)
- **Proved by:** `tests/unit/test_R008_11__a_multi_part_conversion_is_one_container.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4830`, three pages, converted by `pdf-images` | one artifact and one `K_convert`, holding three parts named `page-001.png`, `page-002.png`, `page-003.png` |
| 2 | the same conversion run twice, in two processes with different working directories | byte-identical containers (R8.1 row 2); nothing about the machine or the clock is in them |
| 3 | `PLAY-2002`, which has no text layer | one part; rendering a page does not depend on there being text on it, which is the whole reason this kind exists |
| 4 | a container written and read back | the same ordered parts, so the format has exactly one definition and a converter and a step cannot disagree about it |
| 5 | *counter-example* — the three pages as three artifacts under three keys | not this; R8.4 says one declared conversion is one artifact, and three keys would let R5.4 invalidate a document's pages one at a time |

## Open questions

| # | Question | Resolution |
|---|----------|------------|
| 1 | What is the default `kind` for each media type, beyond `application/pdf → markdown`? | RESOLVED by R8.10 — the table is declared, `image/*` defaults to `page_images`, and anything absent falls back to `markdown` |
