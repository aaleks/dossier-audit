# 15 · Solution

**Read this before you trust a line of it.** Every block below is marked, as
exercise 11's are:

| Mark | Means |
|---|---|
| **[run]** | Run against this repository and the two live servers. The output is what it produced. |
| **[derived]** | Worked out from the code or the spec, not printed by a command. |
| **[shape]** | What to expect, and what to check. Not a transcript. |

Nearly everything is **[run]**. The tasks were run in order, in one pass, on
2026-09-26, against `cwiki.apache.org` (Confluence Data Center 9.2.21) and
`confluence.atlassian.com`. They ran at the commit of `main` that made
`confluence-page-markdown` 1.1.0 (#417), which came after R2.23, R2.24 and
R6.21. The liberties taken in showing it:

- `$L` stands for `python .../resources/look.py`, as the README's setup defines
  it. A `dossier run` line's absolute path is shortened to `…/runs/<id>/`.
- Where a message lists every claimed pair, the list is cut to `[…]`.

Three things this exercise found were fixed after it found them, and tasks 4, 6
and 7 show dossier as it is now. What each one did before is marked
**[derived]**: it is taken from this exercise's first pass, and from the opening
paragraph of the rule that fixed it, not from a run of the current code.

Task 3 and task 7's markers were refreshed on 2026-10-11, against
`confluence-page-markdown` 1.2.0 (#422) and the markers R1.26 (#509) writes: the
setup block, tasks 2 and 3, and task 4's first run were run again, once each
against the two servers, and show what they printed. The tombstone-and-return
syncs of task 7, and tasks 5 and 6, were not run again, and show the
2026-09-26 pass, with the markers worked out from R1.19 and R1.26.

A fourth thing was an open question, and task 8 used to end on it. It was
answered after the pass, by R8.26 and R8.27, and task 8's `convert:` maps were
never run against either server. Their blocks are **[derived]**. The one
**[run]** block among them was run on a folder standing in for
`atlassian-docs`, and says so.

What will differ in yours:

- **Snapshot addresses of pages.** A page is never fetched as the same bytes
  twice (task 5), so `dd/0f/dd0f9582…` is this pass's KIP-110 and no one else's.
  The PNGs' addresses will match, because a file's bytes do not change between
  fetches.
- **Times.** The watermarks, the `rbtoc` digits and the run ids.
- **Anything, if a page has been edited.** Its marker will be higher than `v11`,
  `v15` or `v1`.

## Run the prepared answer

Terminal 1, from the repository root, starts the stub:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
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

**[run]** Run as written, on a fresh workspace, one commit before the pass
below (#416). The converter's 1.1.0 changes no count here:

```console
kafka-kips  0 known · 0 changed · 4 new -> 4 fetched
ledger updated · 4 new snapshots · 0 tombstoned
kafka-kips  4 held · 4 converted · 0 cached
cache updated · 4 converted · 0 cached
run 20260926T042935Z-9144 · …/runs/20260926T042935Z-9144/manifest.json
  extract: 2 document(s) · 0 from cache · 0 failed · tokens not reported
atlassian-docs  0 known · 0 changed · 3 new -> 3 fetched
ledger updated · 3 new snapshots · 0 tombstoned
atlassian-docs  3 held · 3 converted · 0 cached
cache updated · 3 converted · 0 cached
```

Two calls in `calls.jsonl`, one per page. Task 4 says why not four.

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
sources.yaml, line 6: in 'kafka-kips', 'token' holds a credential, and this file is committed to git. Name the variable instead, as `token_env: DOSSIER_CONFLUENCE_TOKEN`, and set its value in the environment (R1.8).
```

The suggested name is built from the source's type, and it carries the
`DOSSIER_` prefix, so it is read from `.env` as well as from the shell (R9.11
row 4). **[derived]** When this exercise was first written, the message
suggested `JIRA_TOKEN` to every source. That name has no prefix, so it is not
read from `.env`. This exercise found it, and R1.8 row 7 fixed it.

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

That was seven requests: one search, one listing of files per page, one fetch
per page, and one download per PNG. **[derived]** It was nine when this exercise
was first written. Each PNG fetched listed its page's files again to find its
download link, which on a page with many files meant one more listing for every
file. KIP-1279's 66 images cost about 130 extra requests. A page's files are now
listed once per sync (R1.18 row 6).

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
kafka-kips      2026-09-26T04:39:22.133285+00:00
$ dossier sync kip-audit
kafka-kips  4 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
$ $L watermarks
kafka-kips      2026-09-26T04:39:26.412605+00:00
```

Two or three requests. **[derived]** The page search went out as

```
(space = KAFKA AND title in (…)) AND type = page AND lastmodified >= "2026-09-24 04:39"
```

That is the watermark, less the 24-hour overlap (R2.4), less one more day,
because CQL reads a bare time in the server's own zone (R1.4, R1.15 row 2). A
page last modified in 2018 is not in that window, so the listing was empty.

A page's `lastmodified` does not move when a file on it does, so a second
search asks which files changed in the same window, site-wide:
`type = attachment AND lastmodified >= "2026-09-24 04:39"` (R1.22). About five
a day change on cwiki. If any did, a third asks which of their pages the query
matches, `(…) AND type = page AND id in (…)`, and neither KIP is among them.
Then nothing else: `attachments()` is called for each **listed** page, and
there were none. Tasks 6 and 7 are about the two ways a sync now
reaches a page its window leaves out.

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
.dossier/snapshots/dd/0f/dd0f9582a9f675e2d88b97ee19ba7c44f7557bd25bb2f3800160b3c479069c1f
20747
$ $L note 67637330 > kip-110.md; wc -c < kip-110.md
8796
$ python -c "import json,sys; p=json.load(open(sys.argv[1],encoding='utf-8')); print(sorted(p))" $P
['_expandable', '_links', 'body', 'extensions', 'id', 'position', 'space', 'status', 'title', 'type', 'version']
```

`convert` gives four artifacts: two notes from `confluence-page-markdown`, and
two `page_images` containers from `png-pages`. A PNG's default kind is
`page_images`, not `markdown` (R8.10). Hold on to that, because it is task 4.

**[run]** The table of contents is in the payload and not in the note:

```console
$ grep -o "rbtoc[0-9]*" $P | sort -u
rbtoc1790397563972
$ grep -c "rbtoc\|toc-macro\|_links\|_expandable" kip-110.md
0
```

`1790397563972` milliseconds after 1970 is `2026-09-26 04:39:23 UTC`, under two
seconds after the sync started. Confluence draws the macro with a CSS class named after
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
39:![36294762-b69219dc-1297-11e8-9537-2d214d677211.png](36294762-b69219dc-1297-11e8-9537-2d214d677211.png)![36294778-d275232e-1297-11e8-8522-368ecda49ac9.png](36294778-d275232e-1297-11e8-8522-368ecda49ac9.png)
47:![zstd-1.3.3-vs-4.png](zstd-1.3.3-vs-4.png)
51:![zstd-1.3.4.png](zstd-1.3.4.png)
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
holds from one it never saw. That is an observation, reported and not settled
here.

**[run]** Text a reader never sees:

```console
$ grep -c "Getting issue details" kip-110.md
0
$ grep -n -A3 "HADOOP-13578" kip-110.md
26:  [HADOOP-13578](https://issues.apache.org/jira/browse/HADOOP-13578)
27-  -
28-- HBase (2.0.0) - 
29-
$ grep -o "Getting issue details" $P | wc -l
3
```

The payload holds Confluence's Jira issue macro as the export view renders it,
a placeholder with a spinner:

```html
<span class="jira-issue" data-jira-key="HADOOP-13578" data-client-id="SINGLE_5aa69414-…_67637330_anonymous">
  <a href="https://issues.apache.org/jira/browse/HADOOP-13578" class="jira-issue-key">…HADOOP-13578</a> -
  <span class="summary">Getting issue details...</span>
  <span class="aui-lozenge … issue-placeholder">STATUS</span>
```

A browser replaces the placeholder with the issue's summary and status, fetched
by script after the page loads, so a reader never sees `Getting issue details...
STATUS`. The note does not have it either: the converter writes the key and its
link and leaves both placeholders out (R8.20 row 8). `STATUS` is not the issue's
status, and a stage that read it could report it as one. The macro's leftover
hyphen (`  -` on line 27) is the separator the page put between the key and the
summary, and stays. A macro whose details were rendered, with no
`issue-placeholder` in it, keeps its summary and status, because they are what a
reader sees (R8.20 row 9). **[derived]** Before `confluence-page-markdown` 1.2.0
(#422), `Getting issue details... STATUS` was in this note three times, and R8.20
named only the table of contents, `<style>` and `<script>` as what it took out.

The `data-client-id` ends in `_anonymous`: the payload records who asked for the
page. A source with a credential would hold a different payload for the same
version. The note leaves the attribute out.

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
<h1 id="KIP57InteroperableLZ4Framing-/*&lt;![CDATA[*/div.rbtoc1790397565647{padding:0px;}div.rbtoc1790397565647ul{margin-left:0px;}div.rbtoc1790397565647li{margin-left:0px;padding-left:0px;}/*]]&gt;*/
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
$ $L ground 62694040 '**Released:** 0.10.0.0'
grounded  62694040  '**Released:** 0.10.0.0'
```

Grounding folds the markdown around words on both sides (R6.20), so the spans
keep the note's `**` and still match.

**[run]** The same fields, quoted as a browser shows them, and one span as an
older note had it:

```console
$ $L ground 67637330 'Released: 2.1.0'
grounded  67637330  'Released: 2.1.0'
$ $L ground 62694040 'Released: 0.10.0.0'
grounded  62694040  'Released: 0.10.0.0'
$ $L ground 62694040 '**Released:**0.10.0.0'
ungrounded  62694040  '**Released:**0.10.0.0'
```

The two payloads write that line differently:

```console
$ grep -o '<strong>Released[^/]*/strong>[^<]*' $($L payload 67637330)
<strong>Released</strong>: 2.1.0
$ grep -o '<strong>Released[^/]*/strong>[^<]*' $($L payload 62694040) | od -c | head -3
0000000   <   s   t   r   o   n   g   >   R   e   l   e   a   s   e   d
0000020   : 302 240   <   /   s   t   r   o   n   g   >   0   .   1   0
0000040   .   0   .   0  \n
$ $L note 62694040 | grep Released
**Released:** 0.10.0.0
```

KIP-57 has a non-breaking space (`302 240`, U+00A0) *inside* the bold. KIP-110
has an ordinary space outside it. The note writes both as a reader sees them.
**[run]** Checked on the converter alone:

```console
$ python - <<'PY'
from dossier.infrastructure.converters.confluence_page_markdown import ConfluencePageMarkdownConverter, markdown
print(ConfluencePageMarkdownConverter.version)
for html in ["<p><strong>Released:\xa0</strong>0.10.0.0</p>", "<p><strong>Released: </strong>0.10.0.0</p>"]:
    print(repr(markdown(html)))
PY
1.2.0
'**Released:** 0.10.0.0'
'**Released:** 0.10.0.0'
```

**This exercise found that line broken.** **[derived]** With
`confluence-page-markdown` 1.0.0, KIP-57's note said `**Released:**0.10.0.0`.
`markdownify` moves whitespace at the edge of an emphasis outside its markers
(`chomp`). It strips every kind of whitespace from the edge, but it puts back a
space only if the edge was an ASCII one. So the non-breaking space was dropped,
and two words a reader sees apart were joined. `Released: 0.10.0.0`, copied
from the page, was `ungrounded`, and the reply file had to say
`**Released:**0.10.0.0`. R8.20 row 7 now says the space is kept. The shared
reader writes every non-breaking space as a space before `markdownify` sees it,
and `html-markdown` reads HTML with the same reader, so it was fixed there too.

Grounding had been doing its job all along. A model is shown the note, not the
page, and a model quoting the note grounds. The lesson for writing reply files
and gold answers still stands: copy spans from the note, and check them with
`locate_span`.

The fix moved the converter to 1.1.0. The version is in every convert key
(R5.4), so every page any workspace had converted with 1.0.0 converts again on
its next `dossier convert`. A note whose bytes changed has a new stage key, and
its stage asks the model again. That is how a converter's fix reaches an answer.
It is also why a reply file, or gold, written from the old note can stop
matching: `**Released:**0.10.0.0` above is now `ungrounded`.

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
written, not a defect.

**[run]** The run:

```console
$ dossier run kip-audit --plan
kip-audit  4 document(s) · model openai:gpt-5.4-mini
no previous run to compare against
! extract: new
1 of 1 step(s) would run · nothing written
$ dossier run kip-audit
run 20260926T043932Z-0d67 · …/runs/20260926T043932Z-0d67/manifest.json
  extract: 2 document(s) · 0 from cache · 0 failed · tokens not reported
$ cat calls.jsonl
{"at": "2026-09-26T04:39:32.156912+00:00", "documents": ["62694040"], "image_sha256": [], "images": 0, "matched": true, "model": "gpt-5.4-mini", "prompt_chars": 5945, "prompt_first_line": "Extract the requested fields from the Kafka Improvement Proposal below.", "schema": true}
{"at": "2026-09-26T04:39:32.170011+00:00", "documents": ["67637330"], "image_sha256": [], "images": 0, "matched": true, "model": "gpt-5.4-mini", "prompt_chars": 9142, "prompt_first_line": "Extract the requested fields from the Kafka Improvement Proposal below.", "schema": true}
$ find runs/20260926T043932Z-0d67 -type f | sort
runs/20260926T043932Z-0d67/extract/62694040.json
runs/20260926T043932Z-0d67/extract/62694040.meta.json
runs/20260926T043932Z-0d67/extract/67637330.json
runs/20260926T043932Z-0d67/extract/67637330.meta.json
runs/20260926T043932Z-0d67/failures.json
runs/20260926T043932Z-0d67/manifest.json
$ find .dossier/cache/stage -name '*.meta.json' | wc -l
2
$ python -c "import json,sys; [print(d['key'], d['media_type']) for d in json.load(open(sys.argv[1]))['plan']['documents']]" $(ls -d runs/* | head -1)/manifest.json
62694040 application/vnd.dossier.confluence-page+json
67637330 application/vnd.dossier.confluence-page+json
67637330/zstd-1.3.3-vs-4.png image/png
67637330/zstd-1.3.4.png image/png
```

The plan and the manifest hold four documents. `extract` ran for two, made two
calls, and wrote two answers and two cache entries. For the PNGs there is
nothing at all.

- **`extract` reads bare `documents`**, which is `documents@markdown` (R3.11).
- **A PNG converts to `page_images`** and never to `markdown` (R8.10). The run's
  documents are every document that converted, whatever kind it converted to,
  which is why the manifest has four.
- **A step does not run for a document that holds nothing of any kind it reads**
  (R6.21). The check is in `application/run.py`, `_reads_nothing`, and a replay
  asks it too, so that a replay never looks for an answer the run never wrote
  (R4.7).

The step line does not mention the PNGs, and that is deliberate. A document a
step never had anything to read in is not a failure, and not news either.

**R6.21 exists because this exercise found the step doing otherwise.** Before
it, `extract` was called for each PNG, and each prompt had nothing between
`<source_document>` and `</source_document>`. The log's third line had
`"prompt_chars": 310`: the 323-byte prompt file, less the 13 characters of
`{{documents}}`. The stub, which had no rule for an empty prompt, answered 422,
and the run stopped. Given a rule, it went on, and the cost showed. Both PNGs
had one stage key, because their input was the same `""` (SHA-256
`e3b0c442…`). The second PNG was served the first one's answer, and the file
under `extract/67637330/zstd-1.3.4.png.json` said
`"document": "67637330/zstd-1.3.3-vs-4.png"`. That paragraph is **[derived]**,
as the opening note says: the current code no longer does it.

`resources/proposal.md` is what the exercise proposed at the time. Where R6.21
differs from it: the proposal wanted the skipped documents reported by name,
and the rule counts only what the step ran for. The proposal would have
extended R6.13, and the rule stands beside it, saying per mode why `per_part`
and `aggregate` were already right.

**[run]** Once more:

```console
$ dossier run kip-audit
run 20260926T043932Z-d456 · …/runs/20260926T043932Z-d456/manifest.json
  extract: 2 document(s) · 2 from cache · 0 failed
$ wc -l < calls.jsonl
2
```

Both from cache, and no new call (R5.5).

## Task 5 — the same version, fetched twice

**[run]**

```console
$ dossier sync kip-audit        # fields: [id, title, space, version, body]
kafka-kips  4 known · 2 changed · 0 new -> 2 fetched
      62694040  b6c4f5b17756ae11b526352273394e2a07060589d92818ff24bdc9bb863a8b52 -> 2f0b9302582fa7320478b4805902cfc8534ade4e2d26b0380e5b25b963fd5162
      67637330  dd0f9582a9f675e2d88b97ee19ba7c44f7557bd25bb2f3800160b3c479069c1f -> 7140d15a5def90e99cea46cd565ef8f7a0810b46a49133819ce220aeac4a7cda
ledger updated · 2 new snapshots · 0 tombstoned
$ $L revisions 67637330
2026-09-26T04:39:22.133285+00:00  .dossier/snapshots/dd/0f/dd0f9582a9f675e2d88b97ee19ba7c44f7557bd25bb2f3800160b3c479069c1f
2026-09-26T04:39:33.594992+00:00  .dossier/snapshots/71/40/7140d15a5def90e99cea46cd565ef8f7a0810b46a49133819ce220aeac4a7cda
$ for s in $($L revisions 67637330 | cut -d" " -f3); do wc -c < $s; grep -o "rbtoc[0-9]*" $s | sort -u; done
20747
rbtoc1790397563972
20747
rbtoc1790397575012
$ cmp -l $($L revisions 67637330 | cut -d" " -f3) | wc -l
16
```

Both pages are fetched again, and the PNGs are not. A declared or changed
`fields:` re-evaluates every *item* (R2.3). An attachment is hashed as received
and never projected, so there is nothing about it to re-evaluate. Each page is
repointed, and the old snapshot is still there. A new content is a new path,
never an overwrite (R0.2).

The two snapshots of `v15` are the same length and differ in 16 bytes.
**[derived]** The render time appears four times in the payload: once in the
macro's `<div>`, and three times in its `<style>`. Of its 13 digits, 4 differ
between `…563972` and `…575012`, and `4 × 4 = 16`.

**[run]**

```console
$ dossier convert kip-audit
kafka-kips  4 held · 2 converted · 2 cached
cache updated · 2 converted · 2 cached
$ $L note 67637330 > kip-110-now.md; cmp kip-110.md kip-110-now.md && echo "the same note"
the same note
$ dossier run kip-audit
warning: the source has moved since run 20260926T043932Z-d456: 62694040 re-snapshotted, 67637330 re-snapshotted
run 20260926T043937Z-cbb8 · …/runs/20260926T043937Z-cbb8/manifest.json
  extract: 2 document(s) · 2 from cache · 0 failed
$ wc -l < calls.jsonl
2
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
to `fields:` does this. An unchanged version is never fetched otherwise (R2.1),
and a change to any other key of the source lists it whole without fetching
(R2.24, task 6).

## Task 6 — an export the server refuses

**[run]**

```console
$ $L watermarks
kafka-kips      2026-09-26T04:39:33.594992+00:00
$ dossier sync kip-audit        # export: pdf added
kafka-kips  4 known · 0 changed · 0 new -> 0 fetched
  kafka-kips: 67637330.pdf failed: GET https://cwiki.apache.org/confluence/spaces/flyingpdf/pdfpageexport.action?pageId=67637330 answered 403 Forbidden: `export: pdf` asks for an export this server refuses. Take `export:` out of the source, or have the export permission granted.
  kafka-kips: 62694040.pdf failed: GET https://cwiki.apache.org/confluence/spaces/flyingpdf/pdfpageexport.action?pageId=62694040 answered 403 Forbidden: `export: pdf` asks for an export this server refuses. Take `export:` out of the source, or have the export permission granted.
ledger updated · 0 new snapshots · 0 tombstoned
2 item(s) failed: 62694040.pdf, 67637330.pdf
$ echo $?
1
$ $L watermarks
kafka-kips      2026-09-26T04:39:33.594992+00:00
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

**Why the exports were asked for at all.** Neither page changed, and task 2's
window returns neither. `export` is a key the connector declares, so adding it
changed the hash of the source's own keys, recorded at the last sync. A sync
that finds that hash changed lists without a window, as `--full` would (R2.24).
Every page was listed, and so asked what it carries: its files, and now its
export. It is a complete listing and not a re-evaluation, so `0 fetched`: no
page and no PNG was fetched, their markers being unchanged (R2.1). That was
five requests: one search, one listing of files per page, and one export per
page.

**[run]** What the ledger remembers, and the next sync:

```console
$ $L owed
kafka-kips      62694040.pdf     carried by 62694040   last failed 2026-09-26T04:39:38.496919+00:00
kafka-kips      67637330.pdf     carried by 67637330   last failed 2026-09-26T04:39:38.496919+00:00
$ dossier sync kip-audit
kafka-kips  4 known · 0 changed · 0 new -> 0 fetched
  kafka-kips: 62694040.pdf failed: GET https://cwiki.apache.org/confluence/spaces/flyingpdf/pdfpageexport.action?pageId=62694040 answered 403 Forbidden: `export: pdf` asks for an export this server refuses. Take `export:` out of the source, or have the export permission granted.
  kafka-kips: 67637330.pdf failed: GET https://cwiki.apache.org/confluence/spaces/flyingpdf/pdfpageexport.action?pageId=67637330 answered 403 Forbidden: `export: pdf` asks for an export this server refuses. Take `export:` out of the source, or have the export permission granted.
ledger updated · 0 new snapshots · 0 tombstoned
2 item(s) failed: 62694040.pdf, 67637330.pdf
$ echo $?
1
$ $L watermarks
kafka-kips      2026-09-26T04:39:33.594992+00:00
$ $L owed
kafka-kips      62694040.pdf     carried by 62694040   last failed 2026-09-26T04:39:41.372137+00:00
kafka-kips      67637330.pdf     carried by 67637330   last failed 2026-09-26T04:39:41.372137+00:00
```

This sync's listing was windowed. The last one had answered under the new keys,
failures or not, so the hash matched (R2.24 row 4). The window returned neither
page. Both exports were still asked for, once each, refused, and reported, and
the watermark is where it was before `export:` was added (R1.20 row 3).

`owed` is what did it (R2.23). A fetch that fails leaves the key's own ledger
row as it was, and here there was no row, since the PDF was never held (R1.9).
So the failure is recorded apart from the rows, with the item carrying the key.
At the next sync, each owed key's item is visited whether the listing returned
it or not. For an owed file, the item's files are listed again and the file is
asked for, and the item itself is not fetched, its marker being unchanged. The
`last failed` time moved: each refusal rewrites it.

**[derived]** Without that table, the second sync would have had nothing to
fail on. It would have exited 0 and moved the watermark past the failure, and
no later sync without `--full` would have mentioned the exports again. This
exercise's first pass saw exactly that against cwiki.apache.org, and R2.23's
opening paragraph cites it. The unit tests for R1.20 row 3 had passed, because
their stand-in server returned the page whatever the window said. The tests for
R2.23 and R2.24 use one that honours the window.

**[run]** `export: pdf` taken out:

```console
$ dossier sync kip-audit        # export: taken out
kafka-kips  4 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
$ echo $?
0
$ $L watermarks
kafka-kips      2026-09-26T04:39:45.109017+00:00
$ $L owed
$ dossier sync kip-audit
kafka-kips  4 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
```

The keys changed back, so this listing was complete too (R2.24). Each page was
listed, and asked what it carries, and neither carries an export any more. An
owed key whose item no longer carries it is owed nothing (R2.23 row 4), so
`owed` is empty. Nothing is tombstoned, because the PDFs were never held.
Nothing failed, so the watermark moves on. The sync after it is windowed and
quiet again.

## Task 7 — an export the server allows

**[run]**

```console
$ dossier sync export-check
atlassian-docs  0 known · 0 changed · 3 new -> 3 fetched
ledger updated · 3 new snapshots · 0 tombstoned
$ $L ledger | grep atlassian
atlassian-docs  792498257                        v1+ic1c15da84414     application/vnd.dossier.confluence-page+json  active
atlassian-docs  792498257.pdf                    v1+ic1c15da84414+292df2727d6b application/pdf                               active
atlassian-docs  792498257/ellipsis.png           792498258:v1         image/png                                     active
$ python -c "import hashlib; print('v1+ic1c15da84414+' + hashlib.sha256(b'792498258:v1').hexdigest()[:12])"
v1+ic1c15da84414+292df2727d6b
```

The page's own marker is no longer `v1` alone: it is `v1+ic1c15da84414`. This
page includes another page's text, which Confluence draws into it without its
version moving, so since R1.26 (#509) the marker is its version, `+i`, and the
first twelve hex digits of the SHA-256 of what it includes, each `<id>:v<n>`,
sorted and joined by newlines. A page including nothing keeps its version alone
(R1.26 row 5), which is why KIP-57 and KIP-110 are still `v11` and `v15`.

The export's marker is the page's marker, as that is now written, a `+`, and the
first twelve hex digits of the SHA-256 of the page's file markers, sorted and
joined by newlines (R1.19). This page carries one file, so that is the hash of
`792498258:v1`. The export of a page carrying no files would have the page's
marker alone (R1.19 row 4): `v1+ic1c15da84414` here.

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
      792498257.pdf  tombstoned
ledger updated · 0 new snapshots · 1 tombstoned
$ $L ledger | grep atlassian
atlassian-docs  792498257                        v1+ic1c15da84414     application/vnd.dossier.confluence-page+json  active
atlassian-docs  792498257.pdf                    v1+ic1c15da84414+292df2727d6b application/pdf                               tombstoned
atlassian-docs  792498257/ellipsis.png           792498258:v1         image/png                                     active
$ dossier sync export-check
atlassian-docs  2 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
$ dossier sync export-check        # export: pdf put back
atlassian-docs  2 known · 0 changed · 0 new · 1 returned -> 0 fetched
      792498257.pdf  returned
ledger updated · 0 new snapshots · 0 tombstoned
$ $L ledger | grep atlassian
atlassian-docs  792498257                        v1+ic1c15da84414     application/vnd.dossier.confluence-page+json  active
atlassian-docs  792498257.pdf                    v1+ic1c15da84414+292df2727d6b application/pdf                               active
atlassian-docs  792498257/ellipsis.png           792498258:v1         image/png                                     active
```

The first sync tombstones the PDF, with no `--full` (R1.19 row 6). The key
changed, so the page was listed without a window (R2.24 row 2), and asked what
it carries. It no longer carries an export, and a file a page no longer carries
is tombstoned (R2.6 row 3). The second sync is windowed again, and quiet (R2.24
row 4).

Put back, the export is active again, and nothing was rendered. The key changed
again, so the page was listed, and `attachments()` reported `792498257.pdf` at
`v1+ic1c15da84414+292df2727d6b`. That is the marker of the snapshot the ledger still held, so
R2.1 skipped the fetch and the row came back as it was. The marker, not the
bytes, decided that the server need not be asked again. A new export would
differ anyway, in the random `/ID` in its trailer.

It is counted and named as `returned`: it was not one of the two rows active
before this sync, and not a key the ledger had never held (R2.25). Until R2.25
the line read `2 known · 0 changed · 0 new -> 0 fetched`, and said nothing
about it.

**[derived]** Before R2.24, the first sync here did nothing, and the PDF stayed
`active` until a `sync --full`. That was this exercise's first pass, and R2.24's
opening paragraph describes the same thing: "taken away it tombstones nothing".
R1.19 row 6's own unit test had passed, for task 6's reason.

## Task 8 — one `convert:` for a whole source, or one per media type

**[run]** The three lists, and none:

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

Each is refused, and all at once, before anything converts (R8.24). A kind
written in a `convert:` list is one the installation has to supply for every
document the source holds. A page is JSON with nothing to draw, and a PNG has no
text, so no list fits a source that holds both. With no `convert:` at all, each
media type gets its default kind (R8.10), and here every default pair is
claimed.

**[derived]** The map:

```console
$ dossier convert kip-audit        # convert: {image/png: [page_images]}
kafka-kips  4 held · 0 converted · 4 cached
cache updated · 0 converted · 4 cached
```

A media type the map names gets the kinds it lists, and one it does not name
gets its default (R8.26). So the PNGs get `page_images`, which was their default
anyway, and the pages get `markdown`. Every artifact is the one the last convert
wrote: a convert key holds the snapshot, the converter and its options, and not
whether the kind was written down or looked up. What did change is who answers
for it. `(image/png, page_images)` is now declared, so an installation that
could not make it would stop the run (R8.24) instead of failing each PNG on its
own (R8.25).

That block was not printed against cwiki.apache.org, and neither are the ones
below. The same map was run on a copy of a workspace synced from cwiki earlier,
holding two other KIPs and the 66 PNGs one of them carries. It printed
`68 held · 0 converted · 68 cached`, and the lists above were refused there as
they are here.

**[derived]** `atlassian-docs`, with the export:

```console
$ dossier convert export-check        # convert: [markdown, page_images]
2 document(s) have no converter:
  792498257 (application/vnd.dossier.confluence-page+json): nothing converts ('application/vnd.dossier.confluence-page+json', 'page_images'). Claimed pairs: […]. …
  792498257/ellipsis.png (image/png): nothing converts ('image/png', 'markdown'). Claimed pairs: […]. …
$ dossier convert export-check        # convert: {application/pdf: [markdown, page_images]}
atlassian-docs  3 held · 1 converted · 3 cached
cache updated · 1 converted · 3 cached
```

**[run]**, on a folder standing in for `atlassian-docs`: `PLAY-1001.md` for the
page's note, `PLAY-2001-terminal-scan.pdf` for its export, and
`terminal-display.png` for the file it carries, all from `playground/corpus/`:

```console
$ dossier sync stand-in
stand-in  0 known · 0 changed · 3 new -> 3 fetched
ledger updated · 3 new snapshots · 0 tombstoned
$ dossier convert stand-in        # no convert:
stand-in  3 held · 3 converted · 0 cached
cache updated · 3 converted · 0 cached
$ dossier convert stand-in        # convert: [markdown, page_images]
2 document(s) have no converter:
  PLAY-1001.md (text/markdown): nothing converts ('text/markdown', 'page_images'). Claimed pairs: […]. A converter is added by installing a package that declares a dossier.converters entry point.
  terminal-display.png (image/png): nothing converts ('image/png', 'markdown'). Claimed pairs: […]. A converter is added by installing a package that declares a dossier.converters entry point.
$ echo $?
2
$ dossier convert stand-in        # convert: {application/pdf: [markdown, page_images]}
stand-in  3 held · 1 converted · 3 cached
cache updated · 1 converted · 3 cached
```

The counts are artifacts, not documents. Under the map the export makes two, its
text and its pages, and the other two documents make one each: four in all, and
only the export's pages are new. The list asks `page_images` of the page, which
has nothing to draw, and `markdown` of the picture, which has no text, and is
refused. That is what spec 008's open question 5 was: it was written about
`page_images` for a page's PDF export, and it applies just as well to a page's
images. R8.26 resolved it. A media type the map names is declared, and one it
does not name keeps its default. A copy of a workspace synced from
confluence.atlassian.com earlier, holding another page with its export and one
PNG, printed the same two answers as the stand-in.

A key is a media type, never an extension: `{pdf: [page_images]}` is refused at
load, naming `pdf` (R8.26 row 6). And a media type mapped to `[]` is not read at
all (R8.27). Exercise 04's task 4 uses that, and shows what it costs.

R6.21 answered the other half: what a step does about a document with nothing of
the kind it reads. With both, a step reading `documents@page_images` over
`atlassian-docs` resolves, because the source was told to make `page_images`
(R4.13). It is asked about the export's pages and about `ellipsis.png`, whose
default kind is `page_images` too, and not about the page, which has none. A
text step reading `documents` is asked about the page's note and the export's
text. Each runs only for what it can read. **[derived]** from R4.13, R6.21 and
R8.10. On the stand-in, a step reading `documents@page_images` was refused
with no `convert:` (R4.13), and with the map it resolved and asked the stub
about the scan's page, one picture in the call.

---

## What this exercise was actually testing

That a source nobody in the room controls can be audited reproducibly. The
evidence is in task 5. Confluence never sent the same bytes twice, and the
ledger kept each fetch as sent. The note came out the same both times, and so
did the stage key, and no model was asked again.

Where the chain from page to answer went wrong, it was never the network's
doing. The first pass of this exercise found three places: a converter that
dropped a space, a step asked about a picture it could not read, and a sync that
never asked again for what it had been refused. They became R8.20 row 7, R6.21,
and R2.23 with R2.24, and tasks 4, 6 and 7 now show each of them working. Each
was found by reading what the workspace holds, which is what this exercise was.

**Back to:** [the playground index](../README.md).
