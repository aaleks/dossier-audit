# 008 — Conversion

**Status:** Implemented
**Rules:** R8.1 – R8.29

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
| no converter claims a pair the source declared in `convert:` | the whole run stops | the pipeline asks for something this installation cannot make. Nothing about the run is well-defined, and the fix is an installation or a correction to `convert:`, not a retry (R8.24) |
| a converter fails on one document | that document only | the configuration is right and one input is bad. An audit over nine of ten documents is useful, provided it says which one is missing |

The first is `UnknownSourceType`'s shape (spec 001), reported before any work
starts. The second is R6.9's shape, reported per document with a non-zero exit.

A source that declares no `convert:` leaves both choices to `dossier`: the kind
comes from the default table (R8.10) and the converter from what is installed
(R8.13). That is the automatic case, and declaring either is an override. When
the automatic choice finds no converter for a document, nobody asked for
anything this installation cannot do: the file is one somebody attached, or
dropped in a folder. So it is the second kind of failure, not the first. The
document is reported with the pair nothing claims, and the rest of its source
converts (R8.25). Two installed converters claiming one pair stop the run
however the kind was chosen. That is an installation to settle, and no
document is the problem.

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

## A page with no text layer

`pdf-markdown` reads a PDF's text layer, and a photocopy has none. `PLAY-2002`
converts to its anchor and nothing else -- correctly, since the conversion
succeeded and the emptiness is the finding -- and no field in it can ever be
`grounded`. A contract that was signed, scanned and filed is that document, and
it is the ordinary case rather than the odd one.

`docling-markdown` is the converter for it. It runs
[Docling](https://github.com/docling-project/docling) (MIT) over the document,
one page at a time: a page with a text layer is read from it, and a page with none
is read by OCR (R8.14). Either way Docling's layout model finds the headings and
tables, so a photocopied table arrives as a table. It ships in this package behind
the `docling` extra and registers through `dossier.converters` like any other
(R8.7).

**Choosing it.** It claims the pair `pdf-markdown` claims,
`(application/pdf, markdown)`, and two claims on one pair are refused rather than
settled by installation order. So it declares itself **opt-in**: it answers only
in a workspace whose `sources.yaml` names it, and a workspace that names nothing
converts exactly as it did before (R8.13).

```yaml
converters: [docling-markdown]

sources:
  - id: incidents-scanned
    type: folder
    path: incidents/scanned
```

The workspace chooses rather than the source because a manifest pins one
converter per pair (R8.9) and a replay recomposes every conversion from that pin
(R4.7). One converter per pair per workspace keeps both true without touching
either. A per-source choice would need a manifest recording which converter read
which document, and no corpus has asked for that yet (open question 3).

**Its models are part of it.** R8.1 forbids a converter reading "a font file
outside its input", because a file that differs between machines makes
`K_convert` describe something other than what was made. Docling reads two sets of
weights from Hugging Face -- a layout model and a table model. They are outside the
input and inside the converter: `docling-markdown`'s version names each by commit,
and every file it reads is checked against the SHA-256 recorded for that commit
before a page is converted (R8.15). *Where* the weights are kept is per machine
(Docling's model folder, `~/.cache/docling/models` by default); *which* weights
they are is not, so their location cannot reach an artifact. RapidOCR's ONNX
models ship inside the `rapidocr` wheel and are pinned with it, as PDFium is
pinned with `pypdfium2`, and the converter names each by path: asked for its
defaults instead, RapidOCR downloads them on first use.

**It never fetches.** Docling's own default is to download a model from Hugging
Face the first time it needs one, at revision `main` -- a floating name, which is
what R0.6 refuses in a model identifier. Conversion is right of the hash boundary
(R0.10). A converter that downloaded would put the network on the path every
artifact is made on, and `main` would put into the artifact whatever Hugging Face
held that day. The weights are fetched once, on purpose, by a person running the
command a failure names.

**What a spike measured** before this was written (Docling 2.130.0, RapidOCR
3.9.2, onnxruntime 1.30.0; Windows 11, CPU only):

- `INC-4830`'s postmortem photocopied at 200 dpi read back with its root cause
  word for word, in about 12 seconds a page. That is slow: a thousand pages is
  over three hours, and `dossier convert` is the place to pay it once, because a
  conversion is cached and reused across runs (see above).
- The same photocopy converted twice, with 1 and with 4 threads, and with
  RapidOCR's inference on torch and on onnxruntime: one artifact, byte for byte.
  Whether that holds on another machine was not measured (open question 2).
- RapidOCR's text-direction classifier turned one line of a clean, upright scan
  into noise -- `H ed ngu e n ng r y e nr c eng` for "At 06:12 CEST on Tuesday 28
  July 2026 …". With it off, the line read correctly. It is off, and a page scanned
  upside down reads worse for it.
- Docling's automatic OCR on a page with no text layer dropped the spaces between
  words (`internalbecausetheserver`) that OCR of the whole page kept. A span quoted
  with its spaces cannot be found in text without them (R6.4), so a page with no
  text layer is OCR'd whole.
- Docling's markdown escapes underscores and HTML by default. A model quotes
  `lb_acq_01`, not `lb\_acq\_01`, so both are off: the artifact is text a span is
  searched in, not markdown for a renderer.

## A Jira issue

The Jira connector holds an issue as the JSON Jira sent (R1.2), and nothing
converted it: `dossier convert` over a Jira source stopped on
`nothing converts ('application/json', 'markdown')` for every issue, so a source
could be synced and never audited. Playground exercise 11 walked into it.

`jira-issue-markdown` converts it. It claims
`(application/vnd.dossier.jira-issue+json, markdown)` -- the type the connector
reports an issue as (R1.14) -- and it ships in this package with the connector,
because a connector whose documents nothing reads is half a source.

**The note.** An issue payload is mostly machinery: avatar URLs, a `self` link on
every nested object, permission ids, a hundred custom fields that are empty. The
note is what a person reading the incident reads -- the key and summary, a few
fields, the description and the comments, in that order -- and nothing else
(R8.16). Dropping the rest is not tidying. Forty kilobytes of avatar URLs in
`{{documents}}` is forty kilobytes a model can find a plausible quote in. Which
fields are kept, and the order, is a decision over the parsed issue, and is made
in `domain`.

**The markup.** The connector reads Jira's REST API version 2, which answers the
description and each comment as *wiki markup* on both Cloud and Data Center:
`h2. Impact`, `{code:sql}`, `[the rollback|https://…]`. They are written as
markdown (R8.17). Two choices go beyond what the library does by default, both
for the reason `docling-markdown` turns its escapes off: the artifact is text a
span is searched in, not markdown for a renderer. Nothing is backslash-escaped,
and Jira's `\r\n` line endings -- which Data Center sends -- become `\n`.

**Existing options considered**, before writing any of it:

| Option | Checked | Covers | Missing |
|---|---|---|---|
| [`jira2markdown`](https://github.com/catcombo/jira2markdown) 0.5.1 | MIT, pure Python over `pyparsing`. Released 2026-08-13, four releases in two years, issues answered | Wiki markup to markdown: headings, lists, tables, code and noformat blocks, panels, quotes, links, mentions, attachments. Its element list is a constructor argument, so escaping can be left out without patching it | Which fields are the document, and the note's shape: the delta, and project-specific |
| pandoc's `jira` reader, through `pypandoc-binary` 1.17 | Pandoc is active and very widely used | The same markup, from a mature parser | A 25–40 MB binary per platform, called as a subprocess, for one field format. The same delta |
| Rendered HTML (`expand=renderedFields`) through `markdownify` | `markdownify` 1.2.3, June 2026, 2.2k stars | Would share one HTML reader with a Confluence converter | Changes the payload every issue is stored as -- a new snapshot of every held issue -- and carries the server's own URLs and macro markup into the note |

**Chosen: `jira2markdown`**, as a dependency of `dossier` itself rather than an
extra, since the connector it serves is not an extra either. It is pinned exactly,
as Docling is: what it writes is inside the artifact, and `K_convert` names the
converter's version, not its library's (R5.4). Upgrading it is a new version of
`jira-issue-markdown`. The Atlassian Document Format, which REST API version 3
answers instead, is not read: the connector never asks version 3.

**A workspace synced before R1.14** holds its issues as `application/json`. The
label is recorded when an issue is fetched (R2.16) and an unchanged issue is not
fetched again (R2.1), so an issue keeps the old label until it next changes, and
convert still refuses it by that pair. Nothing depended on the old label: nothing
converted it. Declaring or changing the source's `fields:` re-fetches every issue
(R2.3), and `fields: [key, fields]` is the projection a Jira source wants anyway
-- it leaves out `self` and `expand`, so a new hostname does not re-snapshot every
issue.

## A Confluence page

The Confluence connector holds a page as the JSON Confluence sends when asked for
the page rendered for export, and labels it
`application/vnd.dossier.confluence-page+json` (R1.17). `confluence-page-markdown`
claims that type with `markdown`. It ships beside the connector for the reason
`jira-issue-markdown` does: a connector whose documents nothing reads is half a
source.

**The note.** `# <title>`; a line each for the space, the version, when it was
written and by whom; then the body (R8.19). The rest of the payload is Confluence's
machinery: `_links`, `_expandable`, and a `self` URL on every nested object. None
of it goes in the note, for the reason R8.16 gives. Which fields are kept, and in
what order, is decided over the parsed page in `domain`.

**The body.** `body.export_view.value` is HTML, and it is written as markdown
(R8.20). The choices are the ones R8.17 made for wiki markup, for the same reason:
the artifact is text a span is searched in, not markdown for a renderer. Nothing is
backslash-escaped, lists use `-`, and headings use `#`. What a reader does not see
is dropped. That means the content of `<style>` and `<script>`, and the table of
contents macro. The table of contents repeats the page's headings, and its class
name holds the time it was rendered, so it would add a sentence that changes on
every fetch. An embedded image is written as the name of the file it shows. The
file is its own document (R1.18). The server's download URL is not kept: it holds
the page's title, and it moves when the page is renamed.

**Existing options considered**, before writing any of it:

| Option | Checked | Covers | Missing |
|---|---|---|---|
| [`markdownify`](https://github.com/matthewwithanm/python-markdownify) 1.2.3 | MIT, pure Python over BeautifulSoup. Released 2026-06-30, six releases since 1.0 | HTML to markdown: headings, lists, tables, code, links and images. Escaping, bullets and heading style are options, and any tag's conversion can be overridden in a subclass | Which fields are the note, the table of contents and the image rule. That is the delta, and it is project-specific |
| [`html-to-markdown`](https://pypi.org/project/html-to-markdown/) 3.14.3 | MIT, released 2026-09-19, with a compiled Rust core in a wheel per platform | The same conversion, faster | Speed is not the constraint here, with one page per request. Every release is a new native binary per platform, inside the artifact's bytes. The same delta |
| pandoc, through `pypandoc-binary` | As for a Jira issue above | The same | A 25–40 MB binary called as a subprocess, as it would have been for Jira |

**Chosen: `markdownify`**, as a dependency of `dossier` itself rather than an
extra, for the reason `jira2markdown` is one. Both `markdownify` and
`beautifulsoup4` are pinned exactly. The parser builds the tree that `markdownify`
writes, so a new release of either can change an artifact under a key that says
nothing changed (R5.4). The same reader is what a `text/html` file would be
converted with.

## An HTML page or a CSV file someone exported

A Jira issue or a Confluence page often carries a file someone exported: a wiki
page saved as HTML, an incident register saved as CSV. Nothing claimed either
pair, so R8.5 stopped the whole source over one attachment. Synced from Apache's
Jira, `KAFKA-20416` carries a `.csv`, a `.jsonl` and an `.html`, and no
document in that source could be converted until they were removed. Two
converters now ship in the core install and answer those pairs by default:
`html-markdown` and `text-csv`.

**HTML** is read with the reader `confluence-page-markdown` uses (R8.20), and the
same choices apply: nothing is escaped, and what a reader of the page does not
see is taken out first (R8.21). In a file, that means the whole `<head>` as
well as `<style>`, `<script>` and `<template>`. Otherwise markdownify writes the
`<title>` into the text as a line of its own, and an export repeats it as the
page's first heading. An image is written as its alt text and the name of its
file (R8.22). An export often inlines its images as `data:` URIs, and markdownify
would put megabytes of base64 into the note.

The bytes are decoded as UTF-8 by the converter, and BeautifulSoup is handed
text, not bytes. Given bytes, BeautifulSoup guesses their encoding with
`charset-normalizer` or `chardet` when either is installed. MLflow brings in
the first, so the same file would decode differently depending on which extras
a machine has, and R8.1 forbids that. A file in another encoding fails, naming
UTF-8, as a text file does (R8.6).

**CSV** is written as the text it is (R8.23). A markdown table was the obvious
alternative and was rejected. A table rewrites every row: `a,b` becomes
`| a | b |`, and a cell holding `|` needs an escape. A model quotes what it is
shown, so a quote from the table would not be found in what the file says, and
the note grows by a third. A person reading a CSV sees its cells, and so does a
model reading its text.

**Existing options considered:**

| Option | Checked | Covers | Missing |
|---|---|---|---|
| `markdownify` 1.2.3, already a core dependency (R8.20) | See "A Confluence page" | HTML to markdown | What is taken out first, and the image rule |
| [`trafilatura`](https://github.com/adbar/trafilatura) | Apache-2.0, active | The main content of a web page, without navigation and advertising | It decides what is boilerplate by heuristic. An export is a document, not a web page, and a heuristic that drops a paragraph drops evidence without a word. A new release would change what counts as boilerplate under an unchanged key |
| `html2text` | GPL-3.0 | HTML to markdown | Its licence would reach everyone who installs `dossier`, as PyMuPDF's AGPL would have (the `pdf` extra) |
| [`tabulate`](https://github.com/astanin/python-tabulate) or [`pytablewriter`](https://github.com/thombashi/pytablewriter), for CSV | MIT, both maintained | A CSV as a markdown table | See **CSV** above. What is missing is the reason to rewrite the file at all |

**Chosen:** `markdownify` for HTML, through the reader R8.20 already pins. No
library for CSV: its text is its note.

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
- **Status:** SUPERSEDED by R8.24

> Superseded because it made no difference who chose the pair. A kind a source
> declares is configuration, and an installation that cannot honour it is a
> pipeline asking for something it cannot have: that still stops the run
> (R8.24). A kind nobody declared was `dossier`'s own choice from the default
> table (R8.10), for a file somebody attached or dropped in a folder. Stopping
> every other document over it let one attachment decide whether a space could
> be audited at all -- `KAFKA-20416`'s `.jsonl` stopped Apache's source. That
> document now fails on its own (R8.25). Row 1 is the case that moved: a `.zip`
> from a source declaring no `convert:` is R8.25's.

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
| 4 | that screenshot, with no converter installed for its pair | the screenshot fails naming `(image/png, page_images)` (R8.25) — the default decides *which* pair must be claimed, never whether one is |
| 5 | *counter-example* — that screenshot, from a source declaring `convert: [markdown]` | `markdown`; a declared kind wins and the table is not consulted at all (R8.3) |

### R8.11 — a conversion that produces several parts produces one artifact, a deterministic container

A page-images conversion of a forty-page PDF is forty pictures. R8.4 says one
declared conversion is one artifact with one key, and that is the right answer:
forty keys would let a version bump invalidate the pages of one document
separately, and no rule anywhere says what a document with nineteen old pages
and twenty-one new ones is.

So the parts travel together, in a container that is a pure function of its
contents. No timestamps, no permissions, no compression -- every one of those is a
property of the machine rather than of the content. Entries in part order. R8.1 already requires the artifact to be byte-identical across
machines; this is what makes that achievable for an artifact that is not one
blob to begin with.

The container's format belongs to `domain` rather than to the converter that
writes it, for the reason the page anchor does (R6.14): a step will read what a
converter wrote, and a format written down twice is one that eventually differs.

It is `domain`'s for the reason the page anchor is (R6.14) and it stays there
even though a ZIP would have been the obvious choice: `zipfile` needs a
file-like object, `io` is on the purity boundary's forbidden list, and
`application` -- where a step unpacks it -- may import nothing but `domain`. The
format gave way rather than the boundary. What that costs is unzipping an
artifact with a standard tool; what it buys is a container with no field in it
that a platform fills in.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.conversion.pack_parts`, `unpack_parts`)
- **Proved by:** `tests/unit/test_R008_11__a_multi_part_conversion_is_one_container.py`, `tests/unit/test_R008_11__pdf_images_renders_every_page.py`
- **Status:** MET

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
| 2 | Is `docling-markdown`'s artifact byte-identical on another machine? It was identical across runs, thread counts and two inference backends on one Windows machine | ANSWERED, with a finding — not for a page read from its text layer. Measured 2026-09-26 on Windows 11 (Python 3.12.13, AMD64) and Linux (`python:3.12-slim`, Python 3.12.14, x86_64), every package at the lock's version and the same input bytes on both. The photocopy and `PLAY-2002` are byte-identical: a page that is a picture renders to the same pixels on both, and Docling's models and RapidOCR read them the same way. The half-photocopy is not. Its page 1, read from its text layer, loses a heading (`Checkout authorisation success rate, % (2026-07-28, CEST)`) on Linux, and two of its tables merge their header row into their first row; pages 2 and 3 are identical. The text layer is the same on both. The page image the layout and table models see is not: the postmortem embeds none of its fonts, so PDFium draws it with whatever fonts the machine has. That is the "font file outside its input" R8.1 row 3 calls a violation, so R8.1 does not hold for a PDF with unembedded fonts. `pdf-images` renders the same way, and its PNGs also differ in bytes for identical pixels, because Pillow's two wheels compress with different zlibs. A run stays reproducible, because a replay reads the artifact the run cached and never converts again (R4.7). A cache shared between machines would hold whichever machine's artifact came first under one `K_convert`. What R8.1 should say about this is not decided here |
| 3 | Should a source, rather than the workspace, choose the converter for a pair? | OPEN — needs a corpus mixing scans with born-digital PDFs where Docling's cost on the digital ones matters. Until then `docling-markdown` reads a digital page from its text layer anyway (R8.14). It is also more than a `sources.yaml` key: a manifest pins one converter per pair, and a replay finds a document's converter by its pair (R4.7), so two sources answering one pair differently need pins per source, a change to spec 004 |
| 4 | Which custom fields belong in a Jira issue's note? The payload names them `customfield_10042`, and what a person calls them comes only with `expand=names`, which changes every payload the connector stores | OPEN — needs a real incident project where a custom field holds what a stage must read. Until then the note holds none (R8.16 row 6) |
| 5 | Should a source declare kinds per media type? `convert:` applies to every document a source holds. So `page_images` for a Confluence page's PDF export (R1.19) is asked of the page JSON too, and nothing claims that pair (R8.24) | RESOLVED by R8.26 and R8.27 — `convert:` may map a media type to its kinds, and a media type mapped to `[]` is not read |
| 6 | Should a CSV saved by Excel in Windows-1252, or an HTML page declaring a legacy `charset`, be read? | OPEN — needs one in a real source. Until then each fails naming UTF-8 (R8.21 row 4, R8.23 row 3), and guessing the encoding is exactly what R8.1 rules out |
| 7 | Should a file nothing claims stop its whole source (R8.5), or only itself? `KAFKA-20416`'s `.jsonl` still stops Apache's source after R8.21–R8.23 | RESOLVED by R8.24 and R8.25 — only itself when its kind was the default, and the run when a source declared it |

### R8.12 — an image converts to `page_images` as a container of one part, and every part is a PNG

R8.10 resolved `image/png` to `page_images` and nothing produced that pair, so
row 4 fired for every image: the default decided which pair had to be claimed
and no converter claimed it. An image source could be synced, held and hashed,
and never converted — the same shape as `page_images` being a kind no step could
name, one layer down.

An image is one page. There is nothing to render and no text to extract: the
conversion is the container (R8.11), so that a step reading `page_images` sees
one interface whatever produced it, and a picture and a forty-page PDF fan out
through the same `per_part` code.

**Every part is a PNG**, whatever the source was. The kind's parts carry no
media type of their own — the composition root labels each one `image/png` when
it unpacks a container — so a JPEG passed through verbatim would be handed to a
provider under the wrong type. A PNG source is therefore copied byte for byte
and a JPEG is re-encoded, which is lossless of the decoded pixels and is the
only work this converter does.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters.image_pages`)
- **Proved by:** `tests/unit/test_R008_12__an_image_converts_to_one_page_image.py`, `tests/acceptance/test_R008_12__an_image_source_runs_end_to_end.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-5720-checkout-latency-postmortem.png`, its source declaring no `convert:` | one `page_images` artifact holding one part, `page-001.png`, byte-identical to the source |
| 2 | a `image/jpeg` source | one part named `page-001.png`, re-encoded; `page_images` parts are PNG so that the type the provider is told is the type it is sent |
| 3 | the same PNG converted twice on two machines | the same artifact bytes; a copy is deterministic. A part that is re-encoded is compressed by one pinned deflate, because Pillow's encoder is deterministic only per build (R8.29) |
| 4 | *counter-example* — a PNG from a source declaring `convert: [markdown]` | R8.24 stops the run naming `(image/png, markdown)`; this converter claims one pair and a declared kind is not it (R8.3) |
| 5 | *counter-example* — a truncated JPEG | that document fails with a reason and the others convert (R8.6); a bad input is not a misconfigured pipeline |

### R8.13 — a pair is answered by the converter `sources.yaml` names for it, and otherwise by the one claimant that is not opt-in

`converters:` in `sources.yaml` names converters by id. A named converter answers
every pair it claims, in place of any other converter claiming that pair. An
opt-in converter answers nothing unless it is named. The decision is made once,
over what is installed, and everything downstream of it -- selection (R8.3), the
manifest (R8.9), a replay (R4.7) -- still sees one converter per pair.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.conversion.answering`)
- **Proved by:** `tests/unit/test_R008_13__a_named_converter_answers_the_pairs_it_claims.py`, `tests/unit/test_R008_13__sources_yaml_names_the_converters_that_answer.py`, `tests/acceptance/test_R008_13__a_workspace_names_the_converter_that_answers.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `docling-markdown` installed beside `pdf-markdown`, `sources.yaml` naming no converter | `OPS-114` is converted by `pdf-markdown` `1.1.0`; an opt-in converter never answers a workspace that did not ask for it, so R8.3 row 1 reads as it always did |
| 2 | `converters: [docling-markdown]` | `OPS-114` is converted by `docling-markdown`, and the manifest pins it and not `pdf-markdown` (R8.9) |
| 3 | the same, `OPS-114`'s source declaring `convert: [markdown, page_images]` | `docling-markdown` and `pdf-images`; a name displaces a converter only on the pairs the named one claims |
| 4 | `converters: [docling-markdwn]` | the command stops before converting anything, naming `docling-markdwn` and the installed converters (R8.5's shape); a misspelt name would otherwise be silently no choice at all |
| 5 | two named converters that both claim `(application/pdf, markdown)` | stops, naming the pair and both; either answer would be picking by the order a list was written in |
| 6 | *counter-example* — two installed converters claiming one pair, neither opt-in, none named | refused as it always was, and the refusal now says that `converters:` in `sources.yaml` settles it |

### R8.14 — `docling-markdown` OCRs a page only when it has no text layer

A page with a text layer is read from it. That text is exact, and OCR is an
estimate of what a picture says: an estimate replacing an exact answer is a loss
even when it is a good estimate. A page whose text layer holds no printable
character is read by OCR, whole. Every page is behind its anchor either way
(R6.14).

Which pages need OCR is a decision over the pages' text layers and is made in
`domain`; reading them is the converter's.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters.docling_markdown`), deciding through domain (`dossier.domain.conversion.ocr_pages`)
- **Proved by:** `tests/unit/test_R008_14__a_page_is_ocred_only_when_it_has_no_text_layer.py`, `tests/integration/test_R008_14__a_photocopied_pdf_converts_to_text.py`, `tests/acceptance/test_R008_14__a_photocopied_postmortem_is_grounded.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4830`'s postmortem photocopied: three pages of pictures and no text layer | three pages behind their anchors, and page 2 reads `Certificate renewal and certificate deployment were two separate processes` -- text a span can be found in (R6.4) |
| 2 | `INC-4830` half-photocopied: page 1 as published, pages 2 and 3 pictures | page 1 read from its text layer, pages 2 and 3 by OCR, three anchors in page order |
| 3 | the photocopy converted twice, in two processes | byte-identical artifacts (R8.1 row 2) |
| 4 | the photocopy in a workspace naming `docling-markdown`, and a stage quoting its root cause | `root_cause` is `grounded` on page 2 (R6.4, R6.14), where `pdf-markdown` would have given it nothing to be grounded in |
| 5 | *counter-example* — `INC-4830` as published | no page is OCR'd; every page has a text layer and is read from it |
| 6 | *counter-example* — `PLAY-2002`, one page holding a 24-pixel picture and nothing else | its anchor and nothing more, and the document converts; OCR finding no text is a finding, not a failure, as it is for `pdf-markdown` |

### R8.15 — `docling-markdown` never fetches a model: one missing, or not at its pinned commit, fails the document naming the command that fetches it

Checked before a page is converted, against the SHA-256 of every file the
converter reads from Docling's model folder. The failure is R8.6's, per document:
the message names the repository, the commit, the file, and the `hf download`
command that puts the right one where it is looked for.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters.docling_markdown`)
- **Proved by:** `tests/unit/test_R008_15__docling_reads_only_the_models_it_pins.py`, `tests/integration/test_R008_15__docling_converts_with_the_network_blocked.py`, `tests/acceptance/test_R008_15__naming_docling_needs_its_models_only_for_a_pdf.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the layout and table models held at their pinned commits, sockets blocked | `INC-4830` photocopied converts; nothing is fetched |
| 2 | no `docling-project--docling-layout-heron` in the model folder | that document fails naming `docling-project/docling-layout-heron`, commit `8f39ad3c`, and `hf download docling-project/docling-layout-heron --revision 8f39ad3c0b4c58e9c2d2c84a38465abf757272d8 --local-dir …`; no socket is opened |
| 3 | `model.safetensors` from a later `main` in that folder | the same failure, naming the file, the SHA-256 it expected and the one it found; the right folder holding the wrong weights is the case nothing else would see |
| 4 | *counter-example* — the folder also holding the model's `README.md` and a picture | converts; only the files the converter reads are checked |
| 5 | *counter-example* — a workspace naming `docling-markdown` whose sources hold only markdown | nothing fails and nothing is checked; a model is needed by a PDF converted with it, not by the name |

### R8.16 — `jira-issue-markdown` converts an issue to a note of its key, summary, fields, description and comments, and of nothing else in the payload

In this order: `# <key> — <summary>`; a line for each of Status, Type, Priority,
Resolution, Created and Updated the issue has, then its attachments by name;
`## Description`; `## Comments`, each comment under its author's display name and
the time Jira wrote beside it. A value is written as Jira sent it: a timestamp is
not re-zoned, because the note may not depend on the machine converting it
(R8.1). An attachment is named and never inlined. It is its own document (R1.6),
and a sentence held by two artifacts is a span that cannot say which one it was
found in.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.jira_issue.note`), called by infrastructure (`dossier.infrastructure.converters.jira_issue_markdown`)
- **Proved by:** `tests/unit/test_R008_16__an_issue_converts_to_a_note_of_what_a_person_reads.py`, `tests/acceptance/test_R008_16__a_jira_issue_is_audited_end_to_end.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821`, summary `Card payments declined at checkout` | the note opens `# INC-4821 — Card payments declined at checkout` |
| 2 | status `Done`, type `Incident`, priority `High`, no resolution | `**Status:** Done`, `**Type:** Incident`, `**Priority:** High`, in that order, under the heading; no `Resolution` line |
| 3 | two comments, `m.keller`'s then `a.aleks`'s | both under `## Comments`, `m.keller`'s first: Jira's order is the thread's order, and sorting it would make a different conversation |
| 4 | `report.pdf` attached | `**Attachments:** report.pdf`, and none of its text |
| 5 | `incidents-jira` synced from Jira, and a stage quoting `CHF 48'200` from `INC-4821`'s description | `loss_amount` is `grounded` (R6.4); before this the issue could not be converted, so no stage ever read it |
| 6 | *counter-example* — the issue's avatar URLs, its `self` links and `customfield_10042` | none of them is in the note |
| 7 | *counter-example* — `{"key": "INC-4821"}`, with no `fields` object | that document fails, naming `jira-issue-markdown` and saying it is not a Jira issue; the source's other documents convert (R8.6) |

### R8.17 — an issue's description and comments are read as Jira wiki markup and written as markdown; its summary and fields are written as text

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters.jira_issue_markdown`)
- **Proved by:** `tests/unit/test_R008_17__wiki_markup_is_written_as_markdown.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a description `h2. Impact`, then `* 42 minutes of declined payments`, its lines ending `\r\n` as Data Center sends them | `## Impact`, then `- 42 minutes of declined payments`, its lines ending `\n` |
| 2 | a comment `see [the rollback|https://git.example/r/77]` | `see [the rollback](https://git.example/r/77)` |
| 3 | a description `pool lb_acq_01 held 3*2 connections` | written as it stands, with no `\_` and no `\*`: a model quotes the text, not an escape |
| 4 | *counter-example* — the summary `*Sev 1* card declines` | the heading keeps `*Sev 1*` as typed; Jira shows a summary as text and never renders it, so neither does the note |

### R8.18 — an issue that holds fewer comments than it counts says so in its note

Jira embeds an issue's comments in its payload and says how many there are in
`comment.total`. A payload holding fewer is a document with part of its thread
missing, and a note that looked complete would let a stage report a thread's
conclusion from its first half.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.jira_issue.note`)
- **Proved by:** `tests/unit/test_R008_18__a_note_says_when_comments_are_missing.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `comment.total` 7, and the payload holding 5 | after the fifth comment, `2 of 7 comments are not in this snapshot.` |
| 2 | *counter-example* — `comment.total` 2, and the payload holding 2 | no such line |
| 3 | *counter-example* — no `comment` field at all | no `## Comments` section, and no such line |

### R8.19 — `confluence-page-markdown` converts a page to a note of its title, space, version, time and author, and its body, and of nothing else in the payload

In this order: `# <title>`, then a line each for `**Space:**`, `**Version:**`,
`**Updated:**` and `**By:**`, then the body. A value is written as Confluence sent
it. A time is not re-zoned, because the note may not depend on the machine
converting it (R8.1).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.confluence_page.note`), called by infrastructure (`dossier.infrastructure.converters.confluence_page_markdown`)
- **Proved by:** `tests/unit/test_R008_19__a_page_converts_to_a_note_of_what_a_person_reads.py`, `tests/acceptance/test_R008_19__a_confluence_page_is_audited_end_to_end.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `81920114`, titled `OPS-114 Incident escalation procedure`, in `OPS`, at version 37, written by `m.keller` at `2026-08-05T16:02:00.000Z` | `# OPS-114 Incident escalation procedure`, then `**Space:** OPS`, `**Version:** 37`, `**Updated:** 2026-08-05T16:02:00.000Z` and `**By:** m.keller`, in that order |
| 2 | `procedures-confluence` synced from Confluence, and a stage quoting a sentence from `81920114`'s body | the value is `grounded` (R6.4). Before this, nothing could sync a Confluence space, so no stage ever read one |
| 3 | *counter-example* — the page's `_links`, its `_expandable`, and its space's `self` URL | none of them is in the note |
| 4 | *counter-example* — `{"id": "81920114"}`, with no `body.export_view` | that document fails, naming `confluence-page-markdown` and saying it is not a rendered Confluence page. The source's other documents convert (R8.6) |

### R8.20 — a page's body is written as markdown, unescaped, and without what a reader does not see

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters.confluence_page_markdown`)
- **Proved by:** `tests/unit/test_R008_20__a_pages_body_is_written_as_markdown.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `<h2>Escalation</h2><ul><li>Page the incident commander</li></ul>` | `## Escalation`, then `- Page the incident commander` |
| 2 | `<a href="https://status.example/rota">the rota</a>` | `[the rota](https://status.example/rota)` |
| 3 | `pool lb_acq_01 held 3*2 connections` | written as it stands, with no `\_` and no `\*` (R8.17 row 3) |
| 4 | an image whose `src` is `…/download/attachments/embedded-page/OPS/…/escalation-matrix.png?api=v2` | `![escalation-matrix.png](escalation-matrix.png)`: the file is named, and the server's URL is not kept |
| 5 | *counter-example* — the table of contents macro, its `<style>` and its `div.toc-macro` | neither is in the note. The headings it lists are there once, where they stand |
| 6 | *counter-example* — text inside an expand macro, hidden until a reader clicks it | kept. A reader who opens the page can read it, so a stage can too |
| 7 | `<strong>Released:&nbsp;</strong>0.10.0.0`, a non-breaking space at the edge of bold | `**Released:** 0.10.0.0`. The space a reader sees is kept: markdownify drops a non-breaking space at the edge of emphasis, and `Released: 0.10.0.0` copied from the page would not be found. Every non-breaking space is written as a space, which the span check's fold does anyway (R6.17) |
| 8 | a Jira issue macro, exported as the key `KAFKA-20186` with its link, then `Getting issue details...` and a `STATUS` lozenge, both marked `issue-placeholder` for a browser to fill in | `[KAFKA-20186](…/browse/KAFKA-20186)`, and neither placeholder. A reader never sees them once the page has loaded. `STATUS` is not the issue's status, and a stage could report it as one |
| 9 | *counter-example* — the same macro with its details rendered, no `issue-placeholder` in it | the summary and status are kept: they are what a reader sees |

### R8.21 — `html-markdown` converts an HTML file to markdown of what a reader sees on the page, unescaped

The page's `<body>`, written as R8.20 writes a Confluence page's body. The
whole `<head>` is taken out, and so are `<style>`, `<script>` and `<template>`
wherever they are.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters.html_markdown`)
- **Proved by:** `tests/unit/test_R008_21__an_html_file_converts_to_what_a_reader_sees.py`, `tests/acceptance/test_R008_21__exported_files_no_longer_stop_a_source.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `PLAY-4001-payment-retries.html` | its breadcrumb, then `# PLAY-4001 — Duplicate payment retries after a queue redelivery`, `**Severity:** major`, and `## Timeline` with its list. The title is there once, as the page's heading, and none of its CSS is. The breadcrumb stays: a reader sees it, and telling navigation from content by class name is the heuristic `trafilatura` was rejected for |
| 2 | a folder source holding `PLAY-4001-payment-retries.html`, `PLAY-4004-incident-register.csv` and `PLAY-2001-terminal-scan.pdf`, declaring no `convert:` | `3 converted`. Before this, `convert` stopped on `(text/html, markdown)` and `(text/csv, markdown)` and converted nothing (R8.5) |
| 3 | `<p>pool lb_acq_01 held 3*2 connections</p>` | written as it stands, with no `\_` and no `\*` (R8.17 row 3) |
| 4 | *counter-example* — an HTML file in Windows-1252 with `é` in it | that document fails, naming `html-markdown` and UTF-8; the source's other documents convert (R8.6) |
| 5 | *counter-example* — a `<script>` in the body holding `var rota = 'on call'` | not in the note; the paragraphs either side of it are |
| 6 | `<p>Released<em>&nbsp;now</em></p>` | `Released *now*`, the space kept, as R8.20 row 7 keeps it |

### R8.22 — an image in an HTML file is written as its alt text and the name of its file, and never as its URL or its data

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters.html_markdown`)
- **Proved by:** `tests/unit/test_R008_22__an_image_is_its_alt_text_and_its_file.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `<img src="panel-checkout-p99.png" alt="Checkout p99 latency">` | `![Checkout p99 latency](panel-checkout-p99.png)` |
| 2 | `PLAY-4003-latency-dashboard-export.html`, whose body is one `<img>` with no alt text | `![panel-checkout-p99.png](panel-checkout-p99.png)`: the file is named, and no text is made up |
| 3 | `<img src="https://grafana.example/render/d/p99.png?from=now-6h">` | `![p99.png](p99.png)`; the host and the query are not kept |
| 4 | *counter-example* — `<img src="data:image/png;base64,iVBORw0KGgo…" alt="Checkout p99 latency">` | `![Checkout p99 latency]()`; none of the base64 is in the note |
| 5 | *counter-example* — `<img src="data:image/png;base64,iVBORw0KGgo…">`, with no alt text | nothing is written for it |

### R8.23 — `text-csv` converts a CSV file to its text as written

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters.text_csv`)
- **Proved by:** `tests/unit/test_R008_23__a_csv_file_converts_to_its_text.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `PLAY-4004-incident-register.csv` | the artifact is the file's bytes, header row first |
| 2 | *counter-example* — the row `PLAY-4001,2026-04-17,major,payments-worker,…` | written with its commas, and no `|` is added: a quote from the row is found in the note as the file has it |
| 3 | *counter-example* — a CSV saved by Excel in Windows-1252 | that document fails, naming `text-csv` and UTF-8 (R8.6) |

### R8.24 — a pair nothing claims stops the run only when the source declared its kind

R8.5's half that still holds. A kind written in `convert:` is a promise the
installation has to keep, and one it cannot keep is known before any work
starts. Every such document is named in one refusal. A kind the source left to
the default table is R8.25's.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.convert`)
- **Proved by:** `tests/unit/test_R008_24__a_declared_pair_nothing_claims_stops_the_run.py`, `tests/acceptance/test_R008_24__a_refusal_in_one_source_converts_nothing_in_another.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `OPS-114`, `application/pdf`, with `pdf-markdown` installed and nothing claiming `page_images`, its source declaring `convert: [page_images]` | the run stops before anything converts. The error names `OPS-114`, `(application/pdf, page_images)`, the claimed pairs and the `dossier.converters` entry point group |
| 2 | `PLAY-4006-indexer-alerts.json` from a folder source declaring `convert: [markdown]` | the same stop, naming `(application/json, markdown)`: `markdown` was asked of every document the source holds, this one included |
| 3 | the same folder also holding `PLAY-4001-payment-retries.html` | no artifact is written, for the HTML either, and no stage runs; the failure is total, like a resolution failure (R4.1) |
| 4 | *counter-example* — `PLAY-4006-indexer-alerts.json` from a folder source declaring no `convert:` | the run does not stop. That document fails on its own (R8.25) |
| 5 | *counter-example* — a second installed converter claiming `(text/html, markdown)` beside `html-markdown`, neither named, the source declaring no `convert:` | the run stops, naming the pair, both converters and `converters:` in `sources.yaml` (R8.13 row 6). It is not reported as documents with no converter: the pair is claimed twice, and no document is at fault |

### R8.25 — a document whose default kind nothing converts fails on its own, and the rest of its source converts

The automatic case. A source declaring no `convert:` gets each document's kind
from the default table (R8.10) and its converter from what is installed
(R8.13). When nothing answers the pair that gives, the document is reported the
way one a converter failed on is (R8.6): named, with a reason that names the
pair, the claimed pairs and the `dossier.converters` entry point group.

The exit is non-zero, as for any document that failed. An audit covering less
than its source holds must not be quotable as a clean one by anything reading
`$?`. The cost is that a source holding a file no converter will ever read
exits non-zero on every run, until the file is gone or a converter is
installed, or the source says it does not want that media type read (R8.27).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.conversion.select`)
- **Proved by:** `tests/unit/test_R008_25__a_default_pair_nothing_claims_fails_its_document.py`, `tests/acceptance/test_R008_25__a_file_nothing_converts_no_longer_stops_its_source.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a folder source declaring no `convert:`, holding `PLAY-4001-payment-retries.html`, `PLAY-4004-incident-register.csv` and `PLAY-4006-indexer-alerts.json` | `dossier convert` reports `3 held · 2 converted · 0 cached` and `PLAY-4006-indexer-alerts.json` failed. Its reason names `(application/json, markdown)`, the claimed pairs and the `dossier.converters` entry point group, and the exit is non-zero |
| 2 | `dossier run` over the same | the stages read the two notes, and `PLAY-4006-indexer-alerts.json` is named as not converted (R8.6). The manifest pins `html-markdown` and `text-csv`, and nothing for the JSON (R8.9) |
| 3 | the same command again, after a package claiming `(application/json, markdown)` is installed | the JSON converts, and the two notes are served from cache. What failed was the installation, and nothing about it was cached |
| 4 | *counter-example* — the same folder declaring `convert: [markdown]` | the run stops before anything converts (R8.24) |

### R8.26 — `convert:` may map a media type to its kinds, and a document whose media type the map does not name gets its default

`convert: [markdown, page_images]` asks both kinds of every document a source
holds. For a Confluence space exporting PDFs (R1.19) that asked `page_images`
of each page's JSON too, and nothing claims that pair. The map says which
documents a kind is for:

```yaml
- id: procedures-confluence
  type: confluence
  export: pdf
  convert:
    application/pdf: [markdown, page_images]
```

A media type the map names is declared, and its kinds follow R8.24: one nothing
claims stops the run. A media type it does not name is left to the default table
(R8.10), and follows R8.25. The list form is unchanged, and still applies to
every document. A key is a media type because the snapshot's media type selects
a converter (R8.3), and a file extension never does.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.conversion.kinds_for`)
- **Proved by:** `tests/unit/test_R008_26__convert_maps_a_media_type_to_its_kinds.py`, `tests/acceptance/test_R008_26__a_vision_step_reads_the_pdfs_of_a_mixed_source.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `procedures-confluence` exporting PDFs, declaring `convert: {application/pdf: [markdown, page_images]}` | `81920114.pdf` converts to `markdown` and `page_images`, and the page `81920114` to `markdown`, its default. Under `convert: [markdown, page_images]` the page's `page_images` stopped the run (R8.24) |
| 2 | a folder source holding `PLAY-2001-terminal-scan.pdf` and `INC-4821.md`, declaring that map, and a step reading `documents@page_images` | the step reads the scan's pages. `INC-4821.md` converts to `markdown` and the step is not asked about it (R6.21), and the run resolves (R4.13): the source was told to make `page_images` |
| 3 | `PLAY-4006-indexer-alerts.json` in a source declaring `convert: {application/pdf: [markdown]}` | fails on its own (R8.25): the map does not name `application/json`, so its kind was the default |
| 4 | `convert: {application/pdf: [page_images]}`, and nothing claiming `(application/pdf, page_images)` | the run stops before anything converts (R8.24): a kind the map names is declared |
| 5 | *counter-example* — `convert: [markdown, page_images]` | every document is asked for both kinds, as it always was (R8.3 row 2) |
| 6 | *counter-example* — `convert: {pdf: [page_images]}` | refused at load, naming `pdf`: a key is a media type such as `application/pdf`, and a file extension is not evidence about content (R8.3 row 4) |

### R8.27 — a media type `convert:` maps to `[]` is not read, and its documents are reported as left out, not failed

R8.25's cost is a source holding a file no converter will ever read: it exits
non-zero on every run. Mapping that media type to no kinds says so in
`sources.yaml`. Its documents are still synced and held (spec 002). They are not
converted, no step reads them, and the report counts them as left out, so the
choice stays visible in every command's output.

It is a declaration and never a default: a file nobody named still fails
(R8.25), so a new kind of attachment is reported the first time it arrives.
`convert: []` is refused at load as it always was (R3.9's reason): for a whole
source, "read nothing" is almost always a mistake.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.convert`)
- **Proved by:** `tests/unit/test_R008_27__a_media_type_mapped_to_nothing_is_left_out.py`, `tests/acceptance/test_R008_27__a_json_export_left_out_on_purpose.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a folder source holding `PLAY-4001-payment-retries.html`, `PLAY-4004-incident-register.csv` and `PLAY-4006-indexer-alerts.json`, declaring `convert: {application/json: []}` | `dossier convert` reports `3 held · 2 converted · 0 cached · 1 left out`, and exits 0 |
| 2 | `dossier run` over the same | two model calls, exit 0. The manifest pins neither the JSON nor a converter for it |
| 3 | *counter-example* — the same folder declaring no `convert:` | `PLAY-4006-indexer-alerts.json` fails, and the exit is non-zero (R8.25). Leaving a file out is something a source says |
| 4 | *counter-example* — `convert: []` | refused at load, as it always was |

### R8.29 — a PNG a converter writes is compressed by one pinned deflate, so its bytes are a function of its pixels

R8.12 row 3 used to say that Pillow's PNG encoder is deterministic on its
documented defaults. It is, per build. Pillow's Windows wheel compresses with zlib-ng and
its Linux wheel with zlib, so the same pixels become different bytes. The
standard library's `zlib` is no better, because CPython on Windows links
zlib-ng too. `dossier` writes each PNG part itself: one row filter,
and the image data compressed by libdeflate (the `deflate` package, pinned).
libdeflate's output depends on its input and its level, and on nothing about
the machine.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.converters._png`)
- **Proved by:** `tests/unit/test_R008_29__a_png_is_a_function_of_its_pixels.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-5720-checkout-latency-postmortem.png`'s pixels, encoded on Windows 11 and on Linux (`python:3.12-slim`) | byte-identical PNGs, `31439acb…`, where Pillow's own encoder gave two. The suite pins the hash, and CI is the second machine |
| 2 | a JPEG source (R8.12 row 2) | its one part re-encoded the same way, and the same bytes on both machines |
| 3 | a part written and read back | the same pixels, size and mode: the PNG is one any reader, and any provider, decodes |
| 4 | *counter-example* — a PNG source (R8.12 row 1) | copied as it is, not re-encoded: its bytes are the input's already |
