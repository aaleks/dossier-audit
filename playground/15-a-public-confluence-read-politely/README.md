# 15 · A public Confluence, read politely

**You will build:** a workspace that syncs two Kafka Improvement Proposals from the
Apache Software Foundation's public Confluence and audits them with the stub
model, and a second source holding one page of Atlassian's own documentation with
its PDF export beside it.

**You will learn:** what the Confluence connector holds and why. A page is keyed
by its id and versioned by its number. The files it carries are documents of
their own. The page is kept as Confluence rendered it, and the note a stage reads
is made from that. You will see what `export: pdf` costs, what a server that
refuses it looks like, and how a sync keeps asking for what it was refused.
You will also see what happens where a source's documents meet a step that
reads only one kind of them, and how a source says which kinds each of its
media types is wanted as.

**Needs network access, and reads servers that belong to other people. Uses the
stub model; no key, no licence, no Docker.**

---

## Read this before you start

Every other exercise except 11 runs offline. This one reads two public
Confluence Data Center servers over the internet: `cwiki.apache.org`, where the
Apache projects keep their wikis, and `confluence.atlassian.com`, where Atlassian
keeps its documentation. Both serve pages to anonymous readers, so you need no
account and write no credential.

You are a guest on both, and behaving like one is part of the exercise:

- **The queries are narrow.** Three pages, named by title or by id, and the four
  files they carry. Do not widen a query to `space = KAFKA` to see what happens.
  That space is thousands of pages, most of them with images, and a first sync
  fetches every one.
- **A sync of an unchanged source is two or three requests.** Task 2 shows
  why. The whole exercise makes forty to fifty.
- **Two tasks ask for a PDF export** (tasks 6 and 7). cwiki refuses it, and
  refusing costs little. confluence.atlassian.com renders one, which is real
  work on someone else's machine. Run each sync the README gives you once, and
  don't add syncs of your own to task 6 while the export is in the source:
  every sync then asks cwiki again, which is the point of the task.
- **Nothing you run can change a page.** Every request is a `GET`, and the
  connector has no method for anything else (R1.1). You cannot rename a page
  either. Task 3 is about a rename you cannot make.

The pages were chosen because nobody edits them any more. KIP-57 was last
changed in 2016, KIP-110 in 2018, and the Atlassian page belongs to the archived
documentation of Confluence 5.9 (2015). If one has been edited since this was
written, its version will be higher, its note may read differently, and a span in
`resources/replies.json` may stop matching. Task 4 shows you how to check a span
against the note you hold.

`SOLUTION.md` marks each block **[run]**, **[derived]** or **[shape]**, as
exercise 11's does. Most of it is **[run]**, but a page is never fetched as the
same bytes twice (task 5), so no snapshot address in it will match yours. Read
its opening note.

---

## Background, in one paragraph

`confluence` is the third connector that ships with `dossier`, after `folder`
and `jira`, and `docs/confluence-connector.md` is the tour of it. A CQL query
scopes a source, as JQL scopes a Jira one. A page is fetched as Confluence
renders it for export, and held as the JSON Confluence sent, labelled
`application/vnd.dossier.confluence-page+json` (R1.17).
`confluence-page-markdown` claims that label and writes the note a stage reads:
the title, a line each for the space, version, time and author, then the body as
markdown (R8.19, R8.20). A page's key is its id and its marker is its version
number (R1.16). Each file it carries is a document of its own, keyed
`<page id>/<filename>` (R1.18). With `export: pdf`, the page also carries its
PDF export, keyed `<page id>.pdf` (R1.19).

---

## Setup

From the repository root:

```bash
mkdir -p playground/work/15
cp -r playground/15-a-public-confluence-read-politely/solution/workspace/pipelines playground/work/15/
cp playground/15-a-public-confluence-read-politely/resources/env.sample playground/work/15/.env
cd playground/work/15

# the helper that reads the ledger, the snapshots and the notes; it only reads
L="../../../.venv/bin/python ../../15-a-public-confluence-read-politely/resources/look.py"
```

The pipeline is copied rather than written, because it is not what this exercise
is about. `kip-audit` has one step, and three fields that every KIP states in its
Status section: `current_state`, `jira_issue` and `released_in`. Read its three
files before you go on. `export-check` is task 7's.

## Task 1 — a source, and a CQL query

Write `sources.yaml` yourself, from `docs/confluence-connector.md`. It has one
`confluence` source, `kafka-kips`. Its `url` is
`https://cwiki.apache.org/confluence`, and its `query` is CQL naming two pages
in the `KAFKA` space by title:

```
KIP-57 - Interoperable LZ4 Framing
KIP-110: Add Codec for ZStandard Compression
```

Get four things wrong on purpose, one at a time. After each one, run
`dossier run kip-audit --plan`, which reads the configuration and nothing else:

1. Write the query without quotes around it.
2. Add `space: KAFKA` as a key of its own.
3. Add `export: docx`.
4. Add `user_env: DOSSIER_CONFLUENCE_USER`, with no `token_env`.

**Checkpoint.** All four are refused at load time with exit code 2, and none of
them makes a request. The first is YAML's doing, not `dossier`'s: the title
holds `: `, which starts a mapping unless the value is quoted. The second is
refused because a space is a clause of the query, not a key the connector
declares (R1.10). The third is refused because `pdf` is the one export there is
(R1.19 row 7). The fourth is half a credential (R1.21 row 4).

With the source right, the plan runs with no network at all (R3.8):

```
kip-audit  0 document(s) · model openai:gpt-5.4-mini
```

## Task 2 — two pages, four documents

```bash
dossier sync kip-audit
$L ledger
```

**Checkpoint.** Four documents from two pages: `62694040`, `67637330`, and two
PNGs keyed `67637330/<filename>`. Work out each of these before you move on:

- **The keys are numbers.** Open KIP-110 in a browser, choose **•••** then
  **Page Information**, and find `67637330` in the address bar. Why is a page
  keyed by its id and never its title (R1.16, R2.7)?
- **The markers.** A page's marker is `v15`, which is Confluence's own version
  number. Check it under **Page History**. A file's marker is `85472219:v1`, its
  attachment id and its version. Read R1.18 for why it needs both: one kind of
  re-upload keeps the id, and the other restarts the version.
- **The files are documents.** `zstd-1.3.4.png` has its own row, snapshot and
  marker. Nothing about KIP-57 has one, because KIP-57 carries no files.

Now sync again, and check the watermark before and after:

```bash
$L watermarks
dossier sync kip-audit
$L watermarks
```

**Checkpoint.** `4 known · 0 changed · 0 new -> 0 fetched`, and the watermark
moves. That sync made two or three requests. An incremental listing adds
`AND lastmodified >= "<since>"` to the query (R1.4, R1.15 row 2). Neither page
has changed in years, so the search returned nothing. A page's `lastmodified`
does not move when a file on it is uploaded again, so the listing also asks
which files anywhere on cwiki changed in that window, and then which of their
pages the query matches: none (R1.22). Nothing else was asked for. Absence in that listing says nothing about deletion, which is why the
connector declares `lists_everything = False` (R1.11). A window that returns
nothing also asks nothing about what a page carries. Keep this in mind for tasks
6 and 7, which are about what a sync does for a page its window cannot see.

## Task 3 — what was held, and what a stage will read

```bash
dossier convert kip-audit
P=$($L payload 67637330)
$L note 67637330 > kip-110.md
```

`$P` is the page as Confluence sent it (R1.2). `kip-110.md` is the note a stage
will be shown. Read both. Then check each of these:

- **Most of the payload is machinery.** List its top-level keys. Neither
  `_links` nor `_expandable` is in the note, and neither is a `self` URL (R8.19
  row 3). The payload is about 20 KB, and the note is about 9 KB.
- **The table of contents.** Run `grep -o "rbtoc[0-9]*" $P`. Read the digits as
  milliseconds since 1970, and compare them with the time you synced. Then look
  for the table of contents in the note (R8.20 row 5), and for the headings it
  listed.
- **A rename you cannot make.** You cannot rename Apache's page, but you can
  find everything a rename would move. Look for the title in the payload's
  `_links.webui`, and in the `src` of each `<img>` in `body.export_view.value`.
  Then find how the note writes the same images. Say what a rename to
  `KIP-110: ZStandard` would change in the ledger, in the note, and in the
  snapshots of the two PNGs (R1.16 row 3, R2.7, R8.20 row 4).
- **Four images in the note, two in the ledger.** `grep -n '!\[' kip-110.md`.
  Where are the other two, and what does the note claim about them?
- **Text a reader never sees.** Look for `Getting issue details...` in the note.
  Find it in the payload, and work out what a browser shows in its place.

Then read the first lines of KIP-57's note (`$L note 62694040 | head -12`). One
line is an empty heading. Find out from the payload why it is there.

## Task 4 — the audit

Start the stub from the repository root, in a second terminal:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
    --replies playground/15-a-public-confluence-read-politely/resources/replies.json \
    --port 8099 --log playground/work/15/calls.jsonl
```

Read `resources/replies.json`. Each span in it was copied out of a note. Check
the spans before you run anything, with the function a run uses to decide
grounding (R6.4):

```bash
$L ground 67637330 '**Released**: 2.1.0'
$L ground 62694040 '**Released:** 0.10.0.0'
```

**Checkpoint.** Both are `grounded`, and so is each release quoted the way a
browser shows it, `Released: 2.1.0` and `Released: 0.10.0.0`. Now find how the
two payloads write that line. They differ, and in KIP-57's the space a reader
sees is not an ordinary one. Read R8.20 row 7: this exercise found that line
turning into `**Released:**0.10.0.0` in the note, so that the quote from the
browser did not ground. What changed in `confluence-page-markdown` to fix it,
and what did the change do to every convert key the converter had written
(R5.4)?

Now the Jira issue. The note links KIP-57's as
`[here](https://issues.apache.org/jira/browse/KAFKA-3160)`. Try the spans
`KAFKA-3160`, `JIRA: here`, and the reply file's span with the issue number
changed to `KAFKA-9999`. Read R6.20 and say what a span quoting a link is
checked against.

Now plan it, and run it:

```bash
dossier run kip-audit --plan
dossier run kip-audit
```

**Checkpoint.** The plan says `4 document(s)`, and the run says
`extract: 2 document(s) · 0 from cache · 0 failed`. `calls.jsonl` has two
lines, and the run's `extract/` folder holds an answer for each page and nothing
for either PNG. Work out why from three rules:

- `extract` reads bare `documents`, which means `documents@markdown` (R3.11).
- A PNG converts to `page_images`, never to `markdown` (R8.10).
- A step does not run for a document that holds nothing of any kind it reads
  (R6.21).

The manifest still lists all four documents, because the run read all four,
and one step had nothing to ask about two of them.

R6.21 exists because this exercise found the step doing otherwise. Before it,
`extract` was called for each PNG with an empty document. Read the rule's
opening paragraph, then `resources/proposal.md`, which is what the exercise
proposed at the time. Say where the rule that landed differs from the proposal.

Run it once more. Both answers are served from cache, and the log does not grow
(R5.5).

## Task 5 — the same version, fetched twice

Add this line to `kafka-kips`, and sync:

```yaml
    fields: [id, title, space, version, body]
```

**Checkpoint.** `2 changed · 0 new -> 2 fetched`. Both pages are re-fetched,
because a changed projection re-evaluates every item in the source (R2.3). The
PNGs are not re-fetched, because a file is never projected. The sync prints two
snapshot addresses for each page. Neither page changed version, so find out why
their bytes did:

```bash
$L revisions 67637330
```

Compare the two snapshots: their sizes, their `rbtoc` classes, and how many
bytes differ (`cmp -l`). Then convert, and compare the note you saved in task 3
with the note you hold now:

```bash
dossier convert kip-audit
$L note 67637330 > kip-110-now.md
cmp kip-110.md kip-110-now.md && echo "the same note"
dossier run kip-audit
```

**Checkpoint.** `2 converted · 2 cached`. The pages are converted again because
their snapshots are new, and the PNGs are not. The notes are the same bytes. The
run warns that the source has moved since the last run. Then every answer is
served from cache, and the log still has two lines. The stage key holds the note, not
the snapshot. Read "Two consequences, accepted" in spec 001's section "A
Confluence page", and say what this would cost against a space of a thousand
pages.

## Task 6 — an export the server refuses

Check the watermark, add `export: pdf` to `kafka-kips`, and sync:

```bash
$L watermarks
dossier sync kip-audit
$L watermarks
$L ledger
```

**Checkpoint.** Exit code 1, and two failures:

```
67637330.pdf failed: GET https://cwiki.apache.org/confluence/spaces/flyingpdf/pdfpageexport.action?pageId=67637330 answered 403 Forbidden: `export: pdf` asks for an export this server refuses. …
```

The pages and the PNGs are still held, and the watermark did not move (R1.20
row 1, R2.8). Say why a refused export is a failure and not a skip. What would a
PDF that went missing without a word look like in the ledger?

Then explain why the exports were asked for at all. Neither page has changed in
years, and task 2 showed a plain sync listing neither. Read R2.24: which key
changed, and what did that change make this sync do?

Now look at what the ledger remembers, and sync again, without changing
anything:

```bash
$L owed
dossier sync kip-audit
$L watermarks
$L owed
```

**Checkpoint.** The listing was windowed this time (R2.24 row 4), and it
returned neither page. Both exports were still asked for, refused, and
reported, and the watermark is still where it was before the export was added.
Read R2.23, and find in `$L owed` what told the sync to visit each page anyway.
What would the next sync have reported if nothing had remembered the failure?

Take `export: pdf` out of `kafka-kips`, and sync once more.

**Checkpoint.** Exit code 0, nothing owed, and the watermark moves on. The PDFs
were never held, so there is nothing to tombstone either (R2.23 row 4).

R2.23 and R2.24 exist because this exercise found a sync that never asked again,
and a key change that nothing noticed. The second proposal in
`resources/proposal.md` is what the exercise suggested at the time. Say how
each rule is wider than the part of the proposal it came from.

## Task 7 — an export the server allows

Add a second source to `sources.yaml`:

```yaml
  - id: atlassian-docs
    type: confluence
    url: https://confluence.atlassian.com
    query: id = 792498257
    export: pdf
```

`pipelines/export-check/` names only this source, so it can be synced and
converted on its own.

```bash
dossier sync export-check
$L ledger
dossier convert export-check
```

**Checkpoint.** Three documents: the page at `v1`, `792498257/ellipsis.png`, and
`792498257.pdf` with the marker `v1+` followed by twelve hex digits. Work out
those digits yourself from R1.19, using the file's marker. Then read the page's
note and the PDF's (`$L note 792498257.pdf`). Where is the image in each, and
why does the export's marker have to move when the image does?

Take `export: pdf` out of `atlassian-docs`, and sync. Sync again. Then put
`export: pdf` back, and sync once more. None of these needs `--full`.

**Checkpoint.** The first sync tombstones `792498257.pdf` (R1.19 row 6), because
a changed key lists the source whole (R2.24 row 2), and a page no longer carries
its export. The second sync is windowed again and does nothing (R2.24 row 4).
After the third, the PDF is active again, and `0 fetched`. What decided that
the server did not need to render it again?

## Task 8 — one `convert:` for a whole source, or one per media type

A vision step would read the PNGs as pictures, and a text step reads the pages
as notes. Try asking for that in `sources.yaml`, one line at a time under
`kafka-kips`, and run `dossier convert kip-audit` after each:

```yaml
    convert: [page_images]
    convert: [markdown]
    convert: [markdown, page_images]
```

**Checkpoint.** All three are refused, each naming the documents it cannot
convert. A list asks every document in the source for every kind in it, and no
list fits a source holding both pages and pictures.

`convert:` has a second form: a map from a media type to the kinds it is wanted
as (R8.26). Try it under `kafka-kips`, and convert again:

```yaml
    convert:
      image/png: [page_images]
```

**Checkpoint.** Nothing is refused, and nothing is converted again. The map
names `image/png`, so the PNGs get what it says. It does not name the pages'
media type, so they get their default kind, as they did with no `convert:` at
all (R8.10).

Now the source the question was first asked about. Task 7's export is a PDF, so
it can be read as pages as well as text, and the page it came from is JSON with
nothing to draw. Take the map out of `kafka-kips`. Then add each of these to
`atlassian-docs` in turn, and run `dossier convert export-check` after each.
Neither makes a request, because `convert` reads only what the workspace holds:

```yaml
    convert: [markdown, page_images]

    convert:
      application/pdf: [markdown, page_images]
```

**Checkpoint.** The list is refused, naming the page and the PNG. The map
converts, and one artifact is new: the export's pages. Read spec 008's open
question 5, and the rules that resolved it. Then connect it to task 4: R6.21
says what a step does about a document with nothing of the kind it reads. Which
question does R8.26 answer that R6.21 does not? With both, which documents
would a step reading `documents@page_images` over `atlassian-docs` be asked
about?

Take the line out again.

---

## Done when

- two pages became four documents, and you can say why each key and each marker
  has the form it has;
- you can say where a rename of KIP-110 would show up and where it would not;
- the audit grounds its spans. You can say why a quote from the browser once
  did not ground, why a value that lives only in a link cannot be quoted, and
  why the step reading `documents` was never asked about the PNGs;
- you saw one page version fetched twice as two snapshots and one note;
- you saw an export refused and one held. You can say why a sync asked for the
  refused export when its window returned no page, and why taking `export:`
  away needed no `--full`;
- you can say why no `convert:` list fits a source holding pages, their files
  and their exports, and which kinds each document gets under a map.

## Cleaning up

```bash
rm -rf playground/work/15
```

Nothing was installed, and no container was started. Nothing needs cleaning up
on either server either, because nothing you ran could change anything there.

**Back to:** [the playground index](../README.md).
