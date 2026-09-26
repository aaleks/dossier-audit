# 01 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

From the repository root:

```bash
mkdir -p playground/work/01/inbox/incidents
cp -r playground/01-first-sync-a-folder-of-notes/solution/workspace/. playground/work/01/
cp playground/corpus/incidents/PLAY-100[1-4].md playground/work/01/inbox/incidents/

cd playground/work/01
../../../.venv/bin/dossier sync incident-audit
```

Everything below is that workspace, task by task.

---

## Task 1 — a workspace that syncs

`playground/work/01/` ends up holding exactly this:

```
sources.yaml
inbox/incidents/PLAY-1001.md … PLAY-1004.md
pipelines/incident-audit/pipeline.yaml
pipelines/incident-audit/prompts/01_extract.md
pipelines/incident-audit/schemas/incident.yaml
```

`sources.yaml` — what *can* be fetched:

```yaml
sources:
  - id: incidents-manual
    type: folder
    path: inbox/incidents/
```

`path` is resolved against the workspace, so the file means the same thing
wherever the workspace is checked out. `folder` is not a branch inside `dossier`:
it is an entry point in the `dossier.connectors` group (R1.7), and `path` is a
key the folder connector itself declares (R1.10) — which is why a misspelling of
it is caught at load time in task 5.

`pipelines/incident-audit/pipeline.yaml` — what this audit needs:

```yaml
sources: [incidents-manual]

model: openai:gpt-5.4-mini

steps:
  - id: extract
    prompt: prompts/01_extract.md
    input: documents
    mode: per_file
    output: schemas/incident.yaml
```

Three things worth noticing now, because they matter in every later exercise:

- The pipeline's **name is its directory name**. It is never written in the file.
- The **model is pinned** and is part of every cache key. Where that model is
  served is `.env`'s business and is in no key (R9.2) — that is what lets
  exercise 02 point this same pipeline at a stub.
- Sync never runs the step. It is here because a pipeline without one does not
  validate.

```console
$ dossier sync incident-audit
incidents-manual  0 known · 0 changed · 4 new -> 4 fetched
ledger updated · 4 new snapshots · 0 tombstoned
```

## Task 2 — what it wrote

```console
$ find .dossier -type f | sort
.dossier/ledger.db
.dossier/snapshots/6b/db/6bdb8cad3ebd2dcf76a24acdf1d36b55a5cda49f0a7222c9809044573892b1d0
.dossier/snapshots/95/0d/950d8ed7fbe310505a8d01cb02233239e3524bd445022b892caa7d6b1ab60007
.dossier/snapshots/9c/5d/9c5d76c1930794d25fd2bb6356a7a4f800ae1f5f9c22ba98b81aec45b67769d4
.dossier/snapshots/d7/c5/d7c5317a23938586cd2ce4d2778373d32693309ab91445e62120bbaa83211ac8
```

The ledger is SQLite, one table of items:

```console
$ python -c "
import sqlite3
con = sqlite3.connect('.dossier/ledger.db')
cur = con.execute('select key, content_hash, media_type, state from items')
for row in cur: print(row)"
('PLAY-1001.md', '6bdb8cad…', 'text/markdown', 'active')
('PLAY-1002.md', '950d8ed7…', 'text/markdown', 'active')
('PLAY-1003.md', '9c5d76c1…', 'text/markdown', 'active')
('PLAY-1004.md', 'd7c5317a…', 'text/markdown', 'active')
```

**Where is the name in the snapshot path?** It is not there, and that is R2.11:
`.dossier/snapshots/<first two>/<next two>/<full hash>`, and nothing else —
not the source id, not the key, not the fetch time. Two consequences fall out of
it: the same bytes arriving from two sources are stored once, and a document
renamed at the source produces no new snapshot at all, only a new ledger key.

**Where did `text/markdown` come from?** From `dossier`, not from the host. The
table is `MEDIA_TYPES` in `src/dossier/domain/conversion.py`, and its comment says
why: `mimetypes.guess_type` reads `/etc/mime.types` on Linux and the registry on
Windows, so the same `.csv` answers differently on two machines. That answer
reaches the ledger, picks the converter and enters every cache key above it — so
a host-dependent guess would fork every hash in the workspace with nothing in any
diff to explain it (R2.16, R5.6).

## Task 3 — the second sync

```console
$ dossier sync incident-audit
incidents-manual  4 known · 0 changed · 0 new -> 4 fetched
ledger updated · 0 new snapshots · 0 tombstoned
```

**Zero snapshots written, four payloads fetched.** Both halves are rules, and
they are deliberately two rules rather than one:

- **R2.14** — a second sync with nothing changed writes zero snapshots. This
  holds for every source, whatever it can say about itself.
- **R2.15** — a second sync fetches *zero payloads* from a source that exposes a
  version marker. A folder exposes none: a file's mtime changes on copy and says
  nothing about content, and R1.5 forbids inventing a version. So the connector
  has to read each file to find out whether it changed, and the content hash
  then decides that nothing did.

A Jira source would have printed `-> 0 fetched` here, because its query answers
"nothing moved" in one request. The costs differ in kind, which is why R2.5 —
which claimed both halves at once — was superseded by the two rules above rather
than patched.

## Task 4 — an edit, and a deletion

```console
$ printf '\n- Added by the reviewer: the credit note was issued on 2026-04-09.\n' >> inbox/incidents/PLAY-1003.md
$ dossier sync incident-audit
incidents-manual  4 known · 1 changed · 0 new -> 4 fetched
      PLAY-1003.md  9b1c…e7f2 -> 4d80…a613
ledger updated · 1 new snapshots · 0 tombstoned

$ find .dossier/snapshots -type f | wc -l
5
```

Five snapshots for four documents. The old bytes of `PLAY-1003.md` are still
there under their own hash, and the ledger row now points at the new one. Nothing
under the snapshot store is ever rewritten (R0.2) — which is what lets a manifest
written before your edit still resolve to the document that run actually read.

The indented line names the item that moved, with the address it held and the
one it holds now — both printed in full, abbreviated here (R2.18). Those are the
two files under `.dossier/snapshots/`, so the edit is one `diff` away:

```console
$ diff .dossier/snapshots/9b/1c/9b1c…e7f2 .dossier/snapshots/4d/80/4d80…a613
```

And the ledger keeps the history after the terminal has scrolled by. Every
address a row has ever held is in `revisions`, oldest first (R2.19):

```console
$ sqlite3 .dossier/ledger.db "select recorded_at, content_hash from revisions where key = 'PLAY-1003.md' order by rowid"
```

Two rows: the first sync's, and this one's.

Now the deletion:

```console
$ rm inbox/incidents/PLAY-1002.md
$ dossier sync incident-audit
incidents-manual  4 known · 0 changed · 0 new -> 3 fetched
      PLAY-1002.md  tombstoned
ledger updated · 0 new snapshots · 1 tombstoned
```

The row is still in the ledger, as `tombstoned` — never deleted — and its
snapshot is still in the store, so a run from before the deletion still resolves
(R2.7). The line under the source names what left (R2.20).

The investigation is *how sync knew it could*. Tombstoning is *held minus
listed*, and that subtraction is only safe against a listing that omitted
nothing: an incremental listing legitimately leaves out everything that did not
change, and subtracting from one would tombstone the quiet majority of a source
— "the most destructive thing sync could do, and it would look like it had
worked" (`tombstones()` in `src/dossier/domain/sync.py`; R1.3, R2.7 row 4). After
your first sync there is a watermark, so sync asked the folder for changes since
yesterday, not for everything.

The folder returned everything anyway. It always does — it has no change time to
narrow by — and it says so: `FolderConnector.lists_everything = True` (R1.11).
`listing_is_complete()` believes a listing for either of two reasons, that sync
asked for everything or that the connector never narrows, and this one qualifies
on the second (R2.21). The Jira connector declares `False`, so a windowed Jira
listing is never subtracted from; an issue deleted at the source is tombstoned by
the next sync that asks for everything, which `dossier sync --full` does on
demand (R2.22).

Until recently the first reason was the only one, and a folder was believed only
on its first sync — a deleted note stayed `active` for ever. The change went
through the repository's own procedure: a spec amendment first (R1.11, R2.21,
R2.22), then the tests, then the code. If you want to see what a rule looks like
when it is written to close a gap someone found in a playground, read those
three.

## Task 5 — three ways to get it wrong

```console
$ cd .. && dossier sync incident-audit
no pipeline 'incident-audit': expected /…/playground/work/pipelines/incident-audit/pipeline.yaml
exit 2
```

It names **where it looked**, not what is missing. The usual cause is being in
the wrong directory, and a message saying "no such pipeline" would send you
looking for the pipeline instead (R2.12).

```console
$ dossier sync incident-audit     # with `pth:` instead of `path:`
sources.yaml, line 4: in 'incidents-manual', unknown key 'pth' -- did you mean 'path'?
exit 2
```

The line number and the suggestion both matter: an unknown key is almost always a
misspelt known one, and a key silently dropped is a source configured differently
from what you wrote (R3.1). Note *who* caught it — the folder connector declares
`path`, and the core checked your file against that declaration without knowing
what a folder is (R1.10).

```console
$ dossier sync incident-audit     # with `token: hunter2` in sources.yaml
sources.yaml, line 5: in 'incidents-manual', 'token' holds a credential, and this file
is committed to git. Name the variable instead, as `token_env: DOSSIER_FOLDER_TOKEN`, and
set its value in the environment (R1.8).
exit 2
```

The message names the file, the line and the key, and never the value — error
messages get pasted into tickets. The check is in the core rather than in each
connector, deliberately: a connector cannot opt its users into committing
credentials, however reasonable the key looks in its own documentation.

---

## What to take to your own project

- Two files, two questions: what *can* be fetched, and what this audit *needs*.
- The ledger is the record of what you hold; the store is the bytes; neither is
  ever edited in place.
- Incremental sync's counts are the interface. "Tomorrow's 420 issues cost 20
  downloads" is only credible because the command prints it (R2.13).
- A safe default sometimes costs something. Find out what it costs before you
  need it at three in the morning.
