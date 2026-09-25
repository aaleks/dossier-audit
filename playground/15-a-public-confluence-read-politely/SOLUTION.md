# 15 · Solution

**Read this before you trust a line of it.** Every block below is marked, as
exercise 11's are:

| Mark | Means |
|---|---|
| **[run]** | Run against this repository and the two live servers. The output is what it produced. |
| **[derived]** | Worked out from the code or the spec, not printed by a command. |
| **[shape]** | What to expect, and what to check. Not a transcript. |

Nearly everything is **[run]**. The tasks were run in order, in one pass, on
2026-09-25, against `cwiki.apache.org` (Confluence Data Center 9.2.21) and
`confluence.atlassian.com`. Tasks 1 to 4, up to the first `dossier run`, were run
a second time, on a fresh workspace and a later commit of `main`, and gave the
same output. Only the snapshot addresses and the render times differed. The
liberties taken in showing it:

- `$L` stands for `python .../resources/look.py`, as the README's setup defines
  it. A `dossier run` line's absolute path is shortened to `…/runs/<id>/`.
- Where a message lists every claimed pair, the list is cut to `[…]`.
- Where a command only saved a file, its file name is the README's.

What will differ in yours:

- **Snapshot addresses of pages.** A page is never fetched as the same bytes
  twice (task 5), so `36/6f/366fa4ea…` is this pass's KIP-110 and no one else's.
  The PNGs' addresses will match, because a file's bytes do not change between
  fetches.
- **Times.** The watermarks, the `rbtoc` digits and the run ids.
- **Anything, if a page has been edited.** Its marker will be higher than `v11`,
  `v15` or `v1`.

## Run the prepared answer

Terminal 1, from the repository root, starts the stub with both reply files:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
    --replies playground/15-a-public-confluence-read-politely/resources/replies-no-document.json \
    --replies playground/15-a-public-confluence-read-politely/resources/replies.json \
    --port 8099 --log playground/work/15/calls.jsonl
```

Terminal 2:

```bash
mkdir -p playground/work/15
cp -r playground/15-a-public-confluence-read-politely/solution/workspace/. playground/work/15/
cp playground/15-a-public-confluence-read-politely/resources/env.sample playground/work/15/.env

cd playground/work/15
D=../../../.venv/bin/dossier
$D sync kip-audit
$D convert kip-audit
$D run kip-audit
$D sync export-check
$D convert export-check
```

Sixteen requests, one of which makes `confluence.atlassian.com` render a PDF.

**[run]** The syncs and conversions were run from this block as written, on a
fresh workspace, and gave the counts tasks 2, 3 and 7 show. **[derived]** The
`run` was not run from here. With both reply files loaded from the start,
expect `extract: 4 document(s) · 1 from cache · 0 failed`: three calls, and the
second PNG served the first PNG's answer. Task 4 explains why.

---

## Task 1 — a source, and a CQL query

**[run]** The four mistakes, each refused before anything is fetched:

```console
$ dossier run kip-audit --plan        # the query unquoted
sources.yaml: not valid YAML -- mapping values are not allowed here
  in "<unicode string>", line 5, column 86:
     ... roperable LZ4 Framing", "KIP-110: Add Codec for ZStandard Compre ...
                                         ^
$ dossier run kip-audit --plan        # space: KAFKA
sources.yaml, line 6: in 'kafka-kips', unknown key 'space'
$ dossier run kip-audit --plan        # export: docx
sources.yaml, line 6: in 'kafka-kips', 'export' -- Input should be 'pdf'
$ dossier run kip-audit --plan        # user_env, and no token_env
sources.yaml, line 2: in 'kafka-kips', `user_env` names a user with no token: name `token_env` as well
```

Each exits with code 2. YAML points at the `: ` inside `KIP-110: Add Codec`. In
block context a plain value cannot contain a colon followed by a space, because
that is how a mapping starts. Quote the whole query, in single quotes, since CQL
wants the double ones:

```yaml
    query: 'space = KAFKA AND title in ("KIP-57 - Interoperable LZ4 Framing", "KIP-110: Add Codec for ZStandard Compression")'
```

`space: KAFKA` is refused because `ConfluenceKeys` declares `url`, `query`,
`token_env`, `user_env` and `export`, and is `extra="forbid"` (R1.10). A space,
a label or a page tree (`ancestor = 81920100`) is a clause of the CQL, and the
connector has no key for any of them. `export` takes one value. `user_env`
alone is refused as a Jira source's is (R1.21 row 4). Which header is sent is
decided by one function both connectors call, `connectors/atlassian.py`.

**[run]** One more, not in the README. `token: hunter2` is refused by key name,
as it is for a Jira source (R1.8):

```console
sources.yaml, line 6: in 'kafka-kips', 'token' holds a credential, and this file is committed to git. Name the variable instead, as `token_env: JIRA_TOKEN`, and set its value in the environment (R1.8).
```

The suggestion names `JIRA_TOKEN` for a Confluence source. That name has no
`DOSSIER_` prefix, so written only in `.env` it would not be read (R9.11 row 4).
The message is shared by every source type, and the name in it was written
when Jira was the only one.

**[run]** With the source right:

```console
$ dossier run kip-audit --plan
kip-audit  0 document(s) · model openai:gpt-5.4-mini
no previous run to compare against
! extract: new
1 of 1 step(s) would run · nothing written
```

Zero documents, no request, no credential (R3.8). Only `sync` builds a
connector.

## Task 2 — two pages, four documents

**[run]**

```console
$ dossier sync kip-audit
kafka-kips  0 known · 0 changed · 4 new -> 4 fetched
ledger updated · 4 new snapshots · 0 tombstoned

$ $L ledger
kafka-kips      62694040                         v11                  application/vnd.dossier.confluence-page+json  active
kafka-kips      67637330                         v15                  application/vnd.dossier.confluence-page+json  active
kafka-kips      67637330/zstd-1.3.3-vs-4.png     85472218:v1          image/png                                     active
kafka-kips      67637330/zstd-1.3.4.png          85472219:v1          image/png                                     active
```

That was nine requests. There was one search and one listing of files per page.
There was one fetch per page, and two requests per PNG: the page's files are
listed again to find the one being fetched, and then it is downloaded
(`ConfluenceConnector._attachment`). For a page with many files, that second
listing is repeated once per file, which is worth knowing before you point a
source at a space full of screenshots.

- **Keys.** `67637330` is KIP-110's page id, the `pageId=` in the address bar
  under **Page Information**. A title is what a person changes when a page is
  renamed, and a key that changes turns an edit into a tombstone and a new item
  (R2.7). So the ledger keys by id, and the note carries the title (R1.16).
- **Markers.** `v15` is Confluence's version number, written with a `v` so it
  reads as a version beside a file's (R1.16). `85472219:v1` is the attachment's
  id and its version. Uploading a file again under the same name keeps the id
  and raises the version. Deleting it and uploading again gives a new id at
  version 1. The id alone misses the first case, and the version alone misses
  the second (R1.18).
- **Files.** Each PNG is a document with its own row, snapshot and marker.
  `item_key` in the ledger names the page that carries it. Its media type is the
  one Confluence records for it, `image/png` (R2.16).

**[run]** The second sync:

```console
$ $L watermarks
kafka-kips      2026-09-25T11:59:35.207041+00:00
$ dossier sync kip-audit
kafka-kips  4 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
$ $L watermarks
kafka-kips      2026-09-25T11:59:39.967300+00:00
```

One request. **[derived]** The search went out as

```
(space = KAFKA AND title in (…)) AND type = page AND lastmodified >= "2026-09-23 11:59"
```

That is the watermark, less the 24-hour overlap (R2.4), less one more day,
because CQL reads a bare time in the server's own zone (R1.4, R1.15 row 2). A
page last modified in 2018 is not in that window, so the listing was empty. An
empty listing asks nothing else: `attachments()` is called for each **listed**
page, and there were none. That matters in tasks 6 and 7.

The connector says of itself that an empty listing proves nothing:

```python
# `since` becomes a CQL clause, so a windowed listing omits every unchanged
# page, and subtracting from one would tombstone most of the space (R1.11).
lists_everything = False
```

## Task 3 — what was held, and what a stage will read

**[run]**

```console
$ dossier convert kip-audit
kafka-kips  4 held · 4 converted · 0 cached
cache updated · 4 converted · 0 cached

$ P=$($L payload 67637330); echo $P; wc -c < $P
.dossier/snapshots/36/6f/366fa4eae0be0b1f6c0389fd5ab045ec93f431fcc92439d6a758a2bbfca2b464
20747
$ $L note 67637330 > kip-110.md; wc -c < kip-110.md
8922
$ python -c "import json,sys; p=json.load(open(sys.argv[1],encoding='utf-8')); print(sorted(p))" $P
['_expandable', '_links', 'body', 'extensions', 'id', 'position', 'space', 'status', 'title', 'type', 'version']
```

`convert` gives four artifacts: two notes from `confluence-page-markdown`, and
two `page_images` containers from `png-pages`. A PNG's default kind is
`page_images`, not `markdown` (R8.10). Hold on to that, because it is task 4.

**[run]** The table of contents is in the payload and not in the note:

```console
$ grep -o "rbtoc[0-9]*" $P | sort -u
rbtoc1790337576015
$ grep -c "rbtoc\|toc-macro\|_links\|_expandable" kip-110.md
0
```

`1790337576015` milliseconds after 1970 is `2026-09-25 11:59:36 UTC`, one second
after the sync started. Confluence draws the macro with a CSS class named after
the moment it drew it, and puts a `<style>` block for that class in front of it.
The converter removes `div.toc-macro`, `style` and `script` before anything is
written (R8.20 row 5), so each heading is in the note once, where it stands:

```console
$ head -20 kip-110.md
# KIP-110: Add Codec for ZStandard Compression

**Space:** KAFKA
**Version:** 15
**Updated:** 2018-11-18T21:50:44.000Z
**By:** Dongjin Lee

# Status

**Current state**: *Accepted*

**Discussion thread**: *[thread1](https://www.mail-archive.com/dev@kafka.apache.org/msg63480.html) [thread2](https://www.mail-archive.com/dev@kafka.apache.org/msg88673.html)*

**JIRA**: [KAFKA-4514](https://issues.apache.org/jira/browse/KAFKA-4514)

**Released**: 2.1.0

Please keep the discussion on the mailing list rather than commenting on the wiki (wiki discussions get unwieldy fast).

# Motivation
```

The four lines under the title are R8.19's, in its order, written as Confluence
sent them. `Updated` is not moved into your time zone, because the note may not
depend on the machine that converts it (R8.1).

**[run]** The rename you cannot make. Everything in the payload that holds the
title:

```console
$ python - $P <<'PY'
import json, re, sys
page = json.load(open(sys.argv[1], encoding="utf-8"))
print("id     ", page["id"])
print("title  ", page["title"])
print("webui  ", page["_links"]["webui"])
for img in re.findall(r"<img [^>]*>", page["body"]["export_view"]["value"]):
    print(re.search(r'class="([^"]*)"', img).group(1), "|", re.search(r'src="([^"]*)"', img).group(1))
PY
id      67637330
title   KIP-110: Add Codec for ZStandard Compression
webui   /spaces/KAFKA/pages/67637330/KIP-110+Add+Codec+for+ZStandard+Compression
confluence-embedded-image confluence-external-resource | https://user-images.githubusercontent.com/89186/36294762-b69219dc-1297-11e8-9537-2d214d677211.png
confluence-embedded-image confluence-external-resource | https://user-images.githubusercontent.com/89186/36294778-d275232e-1297-11e8-8522-368ecda49ac9.png
confluence-embedded-image | https://cwiki.apache.org/confluence/download/attachments/embedded-page/KAFKA/KIP-110:%20Add%20Codec%20for%20ZStandard%20Compression/zstd-1.3.3-vs-4.png?api=v2
confluence-embedded-image | https://cwiki.apache.org/confluence/download/attachments/embedded-page/KAFKA/KIP-110:%20Add%20Codec%20for%20ZStandard%20Compression/zstd-1.3.4.png?api=v2
```

```console
$ grep -n '!\[' kip-110.md
45:![36294762-b69219dc-1297-11e8-9537-2d214d677211.png](36294762-b69219dc-1297-11e8-9537-2d214d677211.png)![36294778-d275232e-1297-11e8-8522-368ecda49ac9.png](36294778-d275232e-1297-11e8-8522-368ecda49ac9.png)
53:![zstd-1.3.3-vs-4.png](zstd-1.3.3-vs-4.png)
57:![zstd-1.3.4.png](zstd-1.3.4.png)
```

**[derived]** A rename of KIP-110 to `KIP-110: ZStandard` would raise the
version to `v16`. The next sync would list the page as `67637330`, find its
marker moved, and fetch it: one changed item, not a tombstone and a new one
(R1.16 row 3). The new snapshot's `_links.webui` and image URLs would hold the
new title. In the note, the heading would change, and so would the version,
time and author lines under it. The image lines would not, because the converter
writes an image as the name of its file and drops the URL (R8.20 row 4). The
PNGs would not be fetched, because renaming a page does not change an
attachment's id or version. Their keys, markers and snapshots would stay as they
are.

A URL that holds the title is also why a projection is not much help here
(task 5). The body is content, and the body is full of absolute URLs.

**Four images in the note, two in the ledger.** The first two `<img>` elements
are `confluence-external-resource`: pictures hot-linked from
`user-images.githubusercontent.com` in 2018, which the page does not carry. No
connector fetched them, and nothing could, since they are not the page's files.
The note still writes them as `![name](name)`, exactly like the two it does
carry. R8.20 writes an image as the file it shows *because* "the file is its own
document (R1.18)". For an external image that reason does not hold. A reader
of the note, whether a person or a model, cannot tell a file this workspace
holds from one it never saw. That is a finding. It has been reported, and it is
not settled here.

**[run]** Text a reader never sees:

```console
$ grep -n -A3 "HADOOP-13578" kip-110.md
26:  [HADOOP-13578](https://issues.apache.org/jira/browse/HADOOP-13578)
27-  -
28-  Getting issue details...
29-  STATUS
```

That is Confluence's Jira issue macro. The export view renders it as a
placeholder with a spinner:

```html
<span class="jira-issue" data-jira-key="HADOOP-13578" data-client-id="SINGLE_5aa69414-…_67637330_anonymous">
  <a href="https://issues.apache.org/jira/browse/HADOOP-13578" class="jira-issue-key">…HADOOP-13578</a> -
  <span class="summary">Getting issue details...</span>
  <span class="aui-lozenge … issue-placeholder">STATUS</span>
```

A browser replaces the placeholder with the issue's summary and status, fetched
by script after the page loads. So `Getting issue details... STATUS` is in the
note three times, and a reader never sees it. It is harmless here, but it is the
kind of sentence R8.20 takes out ("what a reader does not see"), and R8.20
names only the table of contents, `<style>` and `<script>`. The `data-client-id`
ends in `_anonymous`: the payload records who asked for the page. A source with
a credential would hold a different payload for the same version. The note
leaves the attribute out.

**[run]** KIP-57's empty heading:

```console
$ $L note 62694040 | head -12
# KIP-57 - Interoperable LZ4 Framing

**Space:** KAFKA
**Version:** 11
**Updated:** 2016-05-08T16:31:49.000Z
**By:** Dana Powers

# 

# Status

**Current state**: *Accepted*
```

The page's author put the table of contents *inside* a heading, so the payload
opens:

```html
<h1 id="KIP57InteroperableLZ4Framing-/*&lt;![CDATA[*/div.rbtoc1790337579302{padding:0px;}div.rbtoc1790337579302ul{margin-left:0px;}div.rbtoc1790337579302li{margin-left:0px;padding-left:0px;}/*]]&gt;*/#KIP57InteroperableLZ4Framing-
```

The render time is in the heading's `id` too. The converter removes the macro,
the `<h1>` around it is left empty, and it is written as `# `. That is harmless
and correct: the converter wrote what the page was, and the page is odd. It is
worth knowing that a real space is full of pages like this.

## Task 4 — the audit

**[run]** Every span in the reply file, checked with `locate_span` before
anything runs:

```console
$ $L ground 67637330 '**Current state**: *Accepted*'
grounded  67637330  '**Current state**: *Accepted*'
$ $L ground 67637330 '**JIRA**: [KAFKA-4514](https://issues.apache.org/jira/browse/KAFKA-4514)'
grounded  67637330  '**JIRA**: [KAFKA-4514](https://issues.apache.org/jira/browse/KAFKA-4514)'
$ $L ground 67637330 '**Released**: 2.1.0'
grounded  67637330  '**Released**: 2.1.0'
$ $L ground 62694040 '**Current state**: *Accepted*'
grounded  62694040  '**Current state**: *Accepted*'
$ $L ground 62694040 '**JIRA**: [here](https://issues.apache.org/jira/browse/KAFKA-3160)'
grounded  62694040  '**JIRA**: [here](https://issues.apache.org/jira/browse/KAFKA-3160)'
$ $L ground 62694040 '**Released:**0.10.0.0'
grounded  62694040  '**Released:**0.10.0.0'
```

`**Current state**: *Accepted*` is found although the note has a non-breaking
space after the colon. Grounding folds compatibility characters (R6.17) and the
markdown around words (R6.20) on both sides.

**[run]** The same fields, quoted as a browser shows them:

```console
$ $L ground 67637330 'Released: 2.1.0'
grounded  67637330  'Released: 2.1.0'
$ $L ground 62694040 'Released: 0.10.0.0'
ungrounded  62694040  'Released: 0.10.0.0'
$ $L note 62694040 | grep Released
**Released:**0.10.0.0
```

The note has no space between `**Released:**` and `0.10.0.0`, but the page
does. The two payloads show why:

```console
$ grep -o '<strong>Released[^/]*/strong>[^<]*' $($L payload 67637330)
<strong>Released</strong>: 2.1.0
$ grep -o '<strong>Released[^/]*/strong>[^<]*' $($L payload 62694040) | od -c | head -3
0000000   <   s   t   r   o   n   g   >   R   e   l   e   a   s   e   d
0000020   : 302 240   <   /   s   t   r   o   n   g   >   0   .   1   0
0000040   .   0   .   0  \n
```

KIP-57 has a non-breaking space (`302 240`, U+00A0) *inside* the bold.
`markdownify` moves whitespace at the edge of an emphasis outside its markers
(`chomp`). It strips every kind of whitespace from the edge, but it only puts
back a space if the edge was an ASCII one. The non-breaking space is stripped
and never written out, so two words a reader sees apart are joined in the note.
**[run]** Checked on the converter alone:

```console
$ python - <<'PY'
from dossier.infrastructure.converters.confluence_page_markdown import markdown
for html in ["<p><strong>Released:\xa0</strong>0.10.0.0</p>", "<p><strong>Released: </strong>0.10.0.0</p>"]:
    print(repr(markdown(html)))
PY
'**Released:**0.10.0.0'
'**Released:** 0.10.0.0'
```

Grounding is doing its job here. A model is shown the note, not the page, and a
model quoting the note grounds. The lesson for writing reply files, and gold
answers, is to copy spans from the note. The defect is in the converter, and it
has been reported. Confluence's editor puts non-breaking spaces everywhere, so
it will not be rare. `html-markdown` reads HTML with the same reader (R8.21), so
it will have the same defect.

**[run]** A value that lives only in a link:

```console
$ $L ground 62694040 'KAFKA-3160'
ungrounded  62694040  'KAFKA-3160'
$ $L ground 62694040 'JIRA: here'
grounded  62694040  'JIRA: here'
$ $L ground 62694040 '**JIRA**: [here](https://issues.apache.org/jira/browse/KAFKA-9999)'
grounded  62694040  '**JIRA**: [here](https://issues.apache.org/jira/browse/KAFKA-9999)'
```

R6.20 folds `[text](url)` to `text` on both sides. KIP-57's link text is
`here`, so the one place the note says `KAFKA-3160` is a URL, which grounding
never compares. `KAFKA-3160` alone cannot be found. A span quoting the link
grounds on the word `here`, whatever issue it names. The reply file's span is
right, and a span naming `KAFKA-9999` would pass just as well. Keep that in mind
when a value on a wiki page is only ever a link. This is R6.20 working as
written. It is noted in the report, not called a defect.

**[run]** The run, with only `replies.json` loaded:

```console
$ dossier run kip-audit --plan
kip-audit  4 document(s) · model openai:gpt-5.4-mini
no previous run to compare against
! extract: new
1 of 1 step(s) would run · nothing written
$ dossier run kip-audit
kip-audit: POST http://127.0.0.1:8099/api/chat/completions answered 422 Unprocessable Content
$ echo $?
2
$ cat calls.jsonl
{"at": "2026-09-25T12:01:15.672054+00:00", "image_sha256": [], "images": 0, "matched": true, "model": "gpt-5.4-mini", "prompt_chars": 5944, "prompt_first_line": "Extract the requested fields from the Kafka Improvement Proposal below.", "schema": true}
{"at": "2026-09-25T12:01:15.684476+00:00", "image_sha256": [], "images": 0, "matched": true, "model": "gpt-5.4-mini", "prompt_chars": 9251, "prompt_first_line": "Extract the requested fields from the Kafka Improvement Proposal below.", "schema": true}
{"at": "2026-09-25T12:01:15.699800+00:00", "image_sha256": [], "images": 0, "matched": false, "model": "gpt-5.4-mini", "prompt_chars": 310, "prompt_first_line": "Extract the requested fields from the Kafka Improvement Proposal below.", "schema": true}
$ wc -c < pipelines/kip-audit/prompts/01_extract.md
323
```

The plan counts **4** documents, and the third call's prompt is 310
characters. That is the 323-byte prompt file, less the 13 characters of
`{{documents}}`, with nothing in their place. The model was asked to extract
fields from `<source_document></source_document>`.

Keys are taken in order, so the calls were `62694040`, `67637330`, and then
`67637330/zstd-1.3.3-vs-4.png`. The run's documents are every document that
converted, whatever kind it converted to. `ConvertReport.present` says so, and
says why: R6.15 once found a `page_images`-only source running no step at all.
`extract` reads bare `documents`, which is `documents@markdown` (R3.11). A PNG
has only `page_images` (R8.10). For a document with no artifact of the kind it
reads, the step renders an empty string and calls the model anyway:

```python
content = source.get(document)
return "" if content is None else _wrapped(document, content)
```

**[run]** With `replies-no-document.json` in front:

```console
$ dossier run kip-audit
run 20260925T120135Z-5453 · …/runs/20260925T120135Z-5453/manifest.json
  extract: 4 document(s) · 3 from cache · 0 failed · tokens not reported
$ wc -l < calls.jsonl
4
$ find runs/20260925T120135Z-5453 -type f | sort
runs/20260925T120135Z-5453/extract/62694040.json
runs/20260925T120135Z-5453/extract/62694040.meta.json
runs/20260925T120135Z-5453/extract/67637330.json
runs/20260925T120135Z-5453/extract/67637330.meta.json
runs/20260925T120135Z-5453/extract/67637330/zstd-1.3.3-vs-4.png.json
runs/20260925T120135Z-5453/extract/67637330/zstd-1.3.3-vs-4.png.meta.json
runs/20260925T120135Z-5453/extract/67637330/zstd-1.3.4.png.json
runs/20260925T120135Z-5453/extract/67637330/zstd-1.3.4.png.meta.json
runs/20260925T120135Z-5453/manifest.json
$ grep -h '"cache_key"\|"hash"' runs/20260925T120135Z-5453/extract/67637330/*.png.meta.json
  "cache_key": "bead5e726d744d43954269caf2ec161ebac4a1b254a996220a8775fae16feceb",
    "hash": "3f5f7ad268a342882333359c9163d09bc095f4873dab386e86b360426972be05"
      "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "hash": "529518f0e3911f4e95cd871f5121b347950e410288f4e914775beb7ac38c4411",
    "hash": "3a02c31cfc61b3b6ae39d4c44cd4e5a5f1c28537fae8dfdbc7a7d4242c2506d8",
  "cache_key": "bead5e726d744d43954269caf2ec161ebac4a1b254a996220a8775fae16feceb",
    "hash": "3f5f7ad268a342882333359c9163d09bc095f4873dab386e86b360426972be05"
      "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "hash": "529518f0e3911f4e95cd871f5121b347950e410288f4e914775beb7ac38c4411",
    "hash": "3a02c31cfc61b3b6ae39d4c44cd4e5a5f1c28537fae8dfdbc7a7d4242c2506d8",
$ head -2 runs/20260925T120135Z-5453/extract/67637330/zstd-1.3.4.png.json
{
  "document": "67637330/zstd-1.3.3-vs-4.png",
```

The answer filed as `zstd-1.3.4.png` says it is about `zstd-1.3.3-vs-4.png`.
The three answers served from cache are these:

1. **Both pages.** The failed run asked for both before it reached the PNG, and
   each answer was cached as it arrived, before the third call stopped the run.
2. **One PNG**, answered from the entry the *other* PNG's call had just
   written. Both calls had the same input, the empty string, whose SHA-256 is
   `e3b0c442…`. They had the same prompt, schema and model too, so they had one
   stage key, `bead5e72…`. The second PNG's answer was never asked for. It is
   the first PNG's answer, filed under the second PNG's name and still naming
   the first.

So one call about nothing was paid for, where there should have been none, and
one answer in the run says it is about a different document from the one it is
filed under. Neither is grounding's fault, because no span was involved. R6.13
already names every part of this in its reasoning, for a document an earlier
step produced nothing for: "asks a model about a document nobody read, pays for
the call, and caches an answer under a key whose input hash is the hash of
`""`". It does not cover a document that has no artifact of the kind a step
reads. `resources/proposal.md` proposes that it should.

The two recent KIPs this exercise could have used instead carry 66 PNGs
between them. Against those, the first PNG in key order is asked about nothing,
and the other 65 are served its answer, each naming that first PNG.

The answer for a page is what you would expect. The run records the key it
processed, and the three spans are the reply file's:

```json
{
  "document": "62694040",
  "fields": [
    {
      "field": "current_state",
      "value": "accepted",
      "currency": null,
      "reason": null,
      "confidence": "high",
      "source": {
        "document": "62694040",
        "span": "**Current state**: *Accepted*",
        "page": null
      }
    },
    …
  ]
}
```

**[run]** Once more:

```console
$ dossier run kip-audit
run 20260925T120135Z-e7bd · …/runs/20260925T120135Z-e7bd/manifest.json
  extract: 4 document(s) · 4 from cache · 0 failed
$ wc -l < calls.jsonl
4
```

Four from cache and no new call (R5.5).

## Task 5 — the same version, fetched twice

**[run]**

```console
$ dossier sync kip-audit        # fields: [id, title, space, version, body]
kafka-kips  4 known · 2 changed · 0 new -> 2 fetched
      62694040  2ca88e46931a77c8db6ae63a1b78d71589ab07a3e72fb70d2effcbfbaaf44626 -> ede194aae921b3013295cef98a6192012813678c497a3c4873cad9b4e08345b4
      67637330  366fa4eae0be0b1f6c0389fd5ab045ec93f431fcc92439d6a758a2bbfca2b464 -> 3a9de5173532bca487036e6a9dfe71633368d7aa52987e85d2322608a8ac08da
ledger updated · 2 new snapshots · 0 tombstoned
$ $L revisions 67637330
2026-09-25T11:59:35.207041+00:00  .dossier/snapshots/36/6f/366fa4eae0be0b1f6c0389fd5ab045ec93f431fcc92439d6a758a2bbfca2b464
2026-09-25T12:02:01.900793+00:00  .dossier/snapshots/3a/9d/3a9de5173532bca487036e6a9dfe71633368d7aa52987e85d2322608a8ac08da
$ for s in $($L revisions 67637330 | cut -d" " -f3); do wc -c < $s; grep -o "rbtoc[0-9]*" $s | sort -u; done
20747
rbtoc1790337576015
20747
rbtoc1790337722573
$ cmp -l $($L revisions 67637330 | cut -d" " -f3) | wc -l
24
```

Both pages are fetched again, and the PNGs are not. A declared or changed
`fields:` re-evaluates every *item* (R2.3). An attachment is hashed as received
and never projected, so there is nothing about it to re-evaluate. Each page is
repointed, and the old snapshot is still there. A new content is a new path,
never an overwrite (R0.2).

The two snapshots of `v15` are the same length and differ in 24 bytes. The 13
digits of the render time appear four times in the payload, once in the macro's
`<div>` and three times in its `<style>`, and 6 of the 13 differ between
`…576015` and `…722573`: `4 × 6 = 24`. **[derived]**

**[run]**

```console
$ dossier convert kip-audit
kafka-kips  4 held · 2 converted · 2 cached
cache updated · 2 converted · 2 cached
$ $L note 67637330 > kip-110-now.md; cmp kip-110.md kip-110-now.md && echo "the same note"
the same note
$ dossier run kip-audit
warning: the source has moved since run 20260925T120135Z-e7bd: 62694040 re-snapshotted, 67637330 re-snapshotted
run 20260925T120204Z-ce39 · …/runs/20260925T120204Z-ce39/manifest.json
  extract: 4 document(s) · 4 from cache · 0 failed
$ wc -l < calls.jsonl
4
```

The same was true of KIP-57's note. The chain is:

- **The convert key moved, and the converter ran again.** The key is composed
  from the snapshot (R5.4), and the snapshot is new.
- **The note did not move.** The converter removes the only part that changed.
- **The stage key did not move either.** It holds the note's hash, not the
  snapshot's, so the stage was served from cache and no model was asked.

That is spec 001's "Two consequences, accepted", seen from end to end. The
warning is the run saying that the snapshots it read are not the ones the last
run read, before any step runs (R4.9 row 4). It is right, and here it does not
matter.

**[derived]** Against a space of a thousand pages, a change to `fields:` is a
thousand page fetches and a thousand new snapshots, each about as large as the
last. It is also a thousand conversions, and no model call at all. Only a change
to `fields:` does this. An unchanged version is never fetched otherwise (R2.1).

## Task 6 — an export the server refuses

**[run]**

```console
$ dossier sync kip-audit        # export: pdf added
kafka-kips  4 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
$ $L watermarks
kafka-kips      2026-09-25T12:02:19.925469+00:00
```

Nothing happened, for task 2's reason. The listing was windowed, neither page
was in the window, and `attachments()`, which is where a page's export is
listed, is only asked of a listed page. Adding `export:` does not force a
re-evaluation the way a change to `fields:` does. The source configuration hash
covers the projection and nothing else (`domain/sync.py`,
`source_config_hash`, R2.3).

**[run]**

```console
$ dossier sync kip-audit --full
kafka-kips  4 known · 0 changed · 0 new -> 0 fetched
  kafka-kips: 67637330.pdf failed: GET https://cwiki.apache.org/confluence/spaces/flyingpdf/pdfpageexport.action?pageId=67637330 answered 403 Forbidden: `export: pdf` asks for an export this server refuses. Take `export:` out of the source, or have the export permission granted.
  kafka-kips: 62694040.pdf failed: GET https://cwiki.apache.org/confluence/spaces/flyingpdf/pdfpageexport.action?pageId=62694040 answered 403 Forbidden: `export: pdf` asks for an export this server refuses. Take `export:` out of the source, or have the export permission granted.
ledger updated · 0 new snapshots · 0 tombstoned
2 item(s) failed: 62694040.pdf, 67637330.pdf
$ echo $?
1
$ $L watermarks
kafka-kips      2026-09-25T12:02:19.925469+00:00
$ $L ledger
kafka-kips      62694040                         v11                  application/vnd.dossier.confluence-page+json  active
kafka-kips      67637330                         v15                  application/vnd.dossier.confluence-page+json  active
kafka-kips      67637330/zstd-1.3.3-vs-4.png     85472218:v1          image/png                                     active
kafka-kips      67637330/zstd-1.3.4.png          85472219:v1          image/png                                     active
```

This is R1.20 row 1. Each export failed, with the URL, the status, and both
fixes. The pages and their files were untouched (R1.9), and the watermark stayed
where it was (R2.8). cwiki.apache.org serves the page's JSON to anyone and
refuses its PDF to an anonymous reader. That is an administrator's decision,
and the reason spec 001 stopped holding a Confluence page only as a PDF.

A refused export is a failure rather than a skip because `export: pdf` is the
workspace saying the server exports. When it does not, the fix is in
`sources.yaml` or in a permission on the server, and a person has to make it.
Skipped quietly, the ledger would show a page with no `<page id>.pdf`, which is
exactly what a page looks like in a source with no `export:`.

**[run]** Then, without `--full`:

```console
$ dossier sync kip-audit
kafka-kips  4 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
$ echo $?
0
$ $L watermarks
kafka-kips      2026-09-25T12:02:22.361272+00:00
```

**This is not what R1.20 row 3 says.** The row says that at the next sync the
refused export is "asked again as before, once … not dropped from the listing:
a PDF missing without a word reads exactly like a page that has none". Here it
was not asked. Nothing was reported, the exit code was 0, and the watermark
moved past the failure. From now on no sync without `--full` will mention the
two exports again.

Task 2 explains it. Holding the watermark back only helps if the next listing
still includes the page, and a listing windowed by `lastmodified` never includes
a page that has not changed. The unit test for row 3 passes because its first
sync fails *before any watermark exists*, so its second sync is unwindowed too.
Its fake server also ignores the `lastmodified` clause, as a fake can. Against
a real Confluence, the refusal is said once and then never again. This
disagreement between spec and code has been reported. It is not settled here,
and `resources/proposal.md` suggests one way to settle it.

Take `export: pdf` out of `kafka-kips`. Nothing was ever held for it, so there
is nothing to tombstone.

## Task 7 — an export the server allows

**[run]**

```console
$ dossier sync export-check
atlassian-docs  0 known · 0 changed · 3 new -> 3 fetched
ledger updated · 3 new snapshots · 0 tombstoned
$ $L ledger | grep atlassian
atlassian-docs  792498257                        v1                   application/vnd.dossier.confluence-page+json  active
atlassian-docs  792498257.pdf                    v1+292df2727d6b      application/pdf                               active
atlassian-docs  792498257/ellipsis.png           792498258:v1         image/png                                     active
$ python -c "import hashlib; print('v1+' + hashlib.sha256(b'792498258:v1').hexdigest()[:12])"
v1+292df2727d6b
```

The export's marker is the page's marker, a `+`, and the first twelve hex digits
of the SHA-256 of the page's file markers, sorted and joined by newlines
(R1.19). This page carries one file, so that is the hash of `792498258:v1`. A
page carrying no files would have `v1` alone (R1.19 row 4).

**[run]**

```console
$ dossier convert export-check
atlassian-docs  3 held · 3 converted · 0 cached
cache updated · 3 converted · 0 cached
$ $L note 792498257
# Navigating to the Export to PDF Option

**Space:** CONF59
**Version:** 1
**Updated:** 2015-12-02T23:19:49.884Z
**By:** Giles B

You can export a Confluence page to PDF. This option exports a single page and is available to all users who have permission to view the page.

- Go to a page in the space and choose ![ellipsis.png](ellipsis.png) > **Export to PDF** (follow the prompts to export the page)
$ $L note 792498257.pdf
<!-- page 1 -->
Navigating to the Export to PDF Option
You can export a Confluence page to PDF. This option exports a single page and is available to all users who 
have permission to view the page.
Go to a page in the space and choose > Export to PDF (follow the prompts to export the page)
$ head -c 8 $($L payload 792498257.pdf); echo; wc -c < $($L payload 792498257.pdf)
%PDF-1.5
1858
```

A page that says anyone who can view it may export it, exported by an anonymous
reader. The PDF converts through `pdf-markdown`, the default for
`application/pdf` (R8.10). The page's JSON needs a media type of its own,
because only `confluence-page-markdown` can read it (R1.17). The export is just
a PDF, and any PDF converter can read it.

Where the image is in each:

- **In the note**, it is a name, `![ellipsis.png](ellipsis.png)`, and the file
  is its own document.
- **In the PDF**, it is drawn. Reading the PDF's objects finds a 44 × 24 image
  XObject, and its text layer has a gap where the picture is
  (`choose > Export to PDF`).

So when the image is uploaded again in place, the page stays at `v1` and the
PDF changes. That is why the export's marker digests the files' markers. With
the page's marker alone, R2.1 would never fetch the new PDF (R1.19 row 3).

**[run]** Taking the export away, and putting it back:

```console
$ dossier sync export-check        # export: taken out
atlassian-docs  3 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
$ $L ledger | grep atlassian
atlassian-docs  792498257                        v1                   application/vnd.dossier.confluence-page+json  active
atlassian-docs  792498257.pdf                    v1+292df2727d6b      application/pdf                               active
atlassian-docs  792498257/ellipsis.png           792498258:v1         image/png                                     active
$ dossier sync export-check --full
atlassian-docs  3 known · 0 changed · 0 new -> 0 fetched
      792498257.pdf  tombstoned
ledger updated · 0 new snapshots · 1 tombstoned
$ dossier sync export-check --full   # export: pdf put back
atlassian-docs  2 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
$ $L ledger | grep atlassian
atlassian-docs  792498257                        v1                   application/vnd.dossier.confluence-page+json  active
atlassian-docs  792498257.pdf                    v1+292df2727d6b      application/pdf                               active
atlassian-docs  792498257/ellipsis.png           792498258:v1         image/png                                     active
```

R1.19 row 6 says that taking `export:` away tombstones every `<page id>.pdf` "at
the next sync". Against this server, the next sync did nothing. Only `--full`
tombstoned it, and it was tombstoned then as a file its page no longer carries
(R2.6 row 3). The cause is task 6's: a page that is not listed is not asked what
it carries. The row's test gets a listing from a fake that returns the page
however the query is windowed. This is the same disagreement as task 6, and it
was reported with it.

Put back, the export is active again without a request to render it. The page
was listed (`--full`), and `attachments()` reported `792498257.pdf` at
`v1+292df2727d6b`. That is the marker of the snapshot the ledger still held, so
R2.1 skipped the fetch and the row came back as it was. The marker, not the
bytes, decided that the server need not be asked again. A new export would
differ anyway, in the random `/ID` in its trailer.

## Task 8 — one `convert:` for a whole source

**[run]**

```console
$ dossier convert kip-audit        # convert: [page_images]
2 document(s) have no converter:
  62694040 (application/vnd.dossier.confluence-page+json): nothing converts ('application/vnd.dossier.confluence-page+json', 'page_images'). Claimed pairs: […]. A converter is added by installing a package that declares a dossier.converters entry point.
  67637330 (application/vnd.dossier.confluence-page+json): nothing converts ('application/vnd.dossier.confluence-page+json', 'page_images'). Claimed pairs: […]. …
$ dossier convert kip-audit        # convert: [markdown]
2 document(s) have no converter:
  67637330/zstd-1.3.3-vs-4.png (image/png): nothing converts ('image/png', 'markdown'). Claimed pairs: […]. …
  67637330/zstd-1.3.4.png (image/png): nothing converts ('image/png', 'markdown'). Claimed pairs: […]. …
$ dossier convert kip-audit        # convert: [markdown, page_images]
4 document(s) have no converter:
  62694040 (application/vnd.dossier.confluence-page+json): nothing converts ('application/vnd.dossier.confluence-page+json', 'page_images'). …
  67637330 (application/vnd.dossier.confluence-page+json): nothing converts ('application/vnd.dossier.confluence-page+json', 'page_images'). …
  67637330/zstd-1.3.3-vs-4.png (image/png): nothing converts ('image/png', 'markdown'). …
  67637330/zstd-1.3.4.png (image/png): nothing converts ('image/png', 'markdown'). …
$ dossier convert kip-audit        # no convert:
kafka-kips  4 held · 0 converted · 4 cached
cache updated · 0 converted · 4 cached
```

Each is refused, and all at once, before anything converts (R8.5). A page is
JSON with nothing to draw, and a PNG has no text. `convert:` asks every document
in the source for the same kinds, so no list fits a source that holds both. The
only setting that works is none, where each media type gets its default kind
(R8.10).

That is spec 008's open question 5. It was written about `page_images` for a
page's PDF export, and it applies just as well to a page's images. It asks
which kinds each document gets. Task 4's proposal is about a different
question: what a step does about a document that has none of the kind it reads.
Settling the open question would not have saved task 4's call.
`page_images` was already the PNGs' only kind, and the step reading `markdown`
was still asked about them. The two are separate proposals.

---

## What this exercise was actually testing

That a source nobody in the room controls can be audited reproducibly. The
evidence is in task 5. Confluence never sent the same bytes twice, and the
ledger kept each fetch as sent. The note came out the same both times, and so
did the stage key, and no model was asked again. Where the chain from page to
answer *did* go wrong, it was never the network's doing. It was a converter
that dropped a space, a step asked about a picture it could not read, and a
listing that forgets to re-ask. Each of those could be found by reading what the
workspace holds, which is what this exercise was.

**Back to:** [the playground index](../README.md).
