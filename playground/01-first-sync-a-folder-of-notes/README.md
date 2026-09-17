# 01 · First sync of a folder of notes

**You will build:** a workspace from nothing, point `dossier` at a folder of
incident notes, and sync it twice.

**You will learn:** what a workspace is made of, what `sources.yaml` and
`pipeline.yaml` each decide, what the ledger and the snapshot store hold, and why
the second sync writes nothing.

**No model is involved.** `dossier sync` fetches and freezes; nothing here asks a
model anything, so you do not need the stub server until exercise 02.

---

## Background, in one paragraph

`dossier` separates *holding* a document from *auditing* it. Sync fetches what a
source offers, hashes it, and writes anything new to a content-addressed snapshot
store, recording one ledger row per document. Everything above that — conversion,
prompts, scoring — is a pure function of frozen bytes. That is the whole reason a
run from six months ago can be reproduced: the evidence has not moved.

Two files decide what happens:

- **`sources.yaml`** — what *can* be fetched. One entry per source, each with an
  `id`, a `type` and whatever keys that type's connector declares (a `folder`
  declares `path`).
- **`pipelines/<name>/pipeline.yaml`** — what a particular audit *needs*. It
  names sources, a pinned model, and the steps. `dossier sync <pipeline>` syncs
  the sources that pipeline names, not everything in `sources.yaml`.

---

## Task 1 — a workspace that syncs

Create `playground/work/01/` and, inside it:

1. `inbox/incidents/` holding the four notes from `playground/corpus/incidents/`
   (`PLAY-1001.md` … `PLAY-1004.md`).
2. `sources.yaml` declaring one `folder` source with id `incidents-manual`,
   reading `inbox/incidents/`.
3. `pipelines/incident-audit/pipeline.yaml` naming that source, a pinned model,
   and one step. A pipeline with no step is not a valid pipeline, so the step has
   to be there even though sync never executes it. Give the step a prompt file
   and a field declaration — `pipelines/incident-audit/prompts/01_extract.md` and
   `schemas/incident.yaml` — or copy exercise 02's if you would rather get to the
   sync.

Then, from inside the workspace:

```bash
dossier sync incident-audit
```

**Checkpoint.** One line per source and one summary line:

```
incidents-manual  0 known · 0 changed · 4 new -> 4 fetched
ledger updated · 4 new snapshots · 0 tombstoned
```

## Task 2 — look at what it wrote

Nothing in `.dossier/` is a secret. Find:

- the ledger, and the row for `PLAY-1001.md`: its content hash, its media type,
  its `state`;
- the four snapshots. Work out the rule connecting a snapshot's path to its
  content before you look it up (R2.11).

Questions worth answering from what you see:

- Where is the document's *name* in the snapshot path? Why is it not there?
- The ledger records `text/markdown` for these files. Where did that come from —
  the operating system, or `dossier`? (Grep for `MEDIA_TYPES`.)

## Task 3 — sync again, and read the counts

```bash
dossier sync incident-audit
```

**Checkpoint.**

```
incidents-manual  4 known · 0 changed · 0 new -> 4 fetched
ledger updated · 0 new snapshots · 0 tombstoned
```

Four documents were *fetched* and zero snapshots were written. Explain that line
to yourself before moving on — it is R2.14 and R2.15, and the difference between
them is the whole design of incremental sync. What would a Jira source have
printed instead, and why can a folder not do the same?

## Task 4 — change one note, and delete another

Append a line to `PLAY-1003.md`, then sync. Then delete `PLAY-1002.md` and sync
again.

**Checkpoint.** After the edit: `1 changed`, `1 new snapshots`. Count the files
under `.dossier/snapshots/` — there are now five for four documents. The old
bytes are still there, addressed by their own hash. That is R0.2, and it is what
lets a run from before your edit still resolve.

After the delete: something you may not expect. Read the counts carefully, look
at the ledger row for `PLAY-1002.md`, and then work out *why* — the answer is in
`tombstones()` in `src/dossier/domain/sync.py` and in R2.7's fourth row. This is
the investigation of this exercise; take a minute on it before opening the
solution.

## Task 5 — three ways to get it wrong

Each of these is a message worth having seen once:

1. Run `dossier sync incident-audit` from the wrong directory.
2. Misspell a connector key: write `pth:` instead of `path:`.
3. Write a credential into `sources.yaml`: add `token: hunter2` to the source.

**Checkpoint.** All three exit 2 and name the file, the line and the fix. The
third is worth reading twice: it names the key and never the value, and it tells
you what to write instead (R1.8).

---

## Done when

- two syncs, with the second writing zero snapshots;
- you can say what the ledger holds and what the store holds, and why a snapshot
  path has no filename in it;
- you can explain what happened to the deleted note, and why that is deliberate.

**Next:** [02 · A pipeline end to end on markdown](../02-a-pipeline-end-to-end-on-markdown/).
