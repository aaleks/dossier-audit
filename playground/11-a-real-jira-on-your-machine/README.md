# 11 · A real Jira on your machine

**You will build:** a Jira Data Center in Docker, four incidents inside it, and a
`dossier` workspace that syncs and audits them over HTTP.

**You will learn:** what a remote source costs that a folder does not — a
credential that is named and never written, a version marker that belongs to
someone else, a listing that cannot tell you about a deletion, and a payload
that is mostly machinery, where which fields make up the document is a decision
somebody has to make.

---

## Read this before you start

Every other exercise here runs offline, in seconds, at zero cost. **This one does
not**, and the difference is the point of it — the sources people actually audit
are remote, authenticated and slow.

What it costs:

- **A licence.** Jira Server is end of life; Jira Data Center needs a key. The
  free 30-day evaluation one is issued by my.atlassian.com against an Atlassian
  account. There is no perpetual free on-prem Jira, and no way around this step.
- **About 4 GB of RAM** while it is up, and three to five minutes to boot.
- **An interactive setup wizard** that cannot be scripted away.

What it does *not* cost: a model bill. The stub model from `toolkit/` answers the
audit exactly as it does in exercise 02. Only the source is real.

`SOLUTION.md` is therefore different from every other one in this playground.
Where its output came from a live Jira it says so, and where it could not it
shows the shape and says that too. Read its opening note.

---

## Background, in one paragraph

A connector is a package declaring an entry point, and `jira` is one of the two
that ship (R1.7). Everything it does is a `GET` — there is no method on the class
that creates, transitions or marks anything as seen, which is the strongest form
that promise takes (R1.1). Two things about it are worth having in mind before
you start. An issue and each file it carries are **separate addresses** with
separate ledger rows, snapshots and version markers (R1.6). And its listing is
**incomplete by construction**: `since` becomes a JQL clause, so an unchanged
issue is simply absent, and sync must not read absence as deletion (R1.11).

---

## Task 1 — bring Jira up

From the repository root:

```bash
docker compose -f playground/11-a-real-jira-on-your-machine/docker-compose.yml up -d
docker compose -f playground/11-a-real-jira-on-your-machine/docker-compose.yml logs -f jira
```

Then open <http://localhost:8080> and work through the wizard. You will need to
fetch an evaluation licence; the wizard links to it. Choose **English**, let it
create the administrator account, and remember the username and password — they
are the credential for everything below.

```bash
.venv/bin/python playground/11-a-real-jira-on-your-machine/seed_jira.py wait
```

**Checkpoint.** `Jira is RUNNING at http://localhost:8080`. If it says
`FIRST_RUN`, the port is open and the wizard is not finished.

Read `docker-compose.yml` before moving on, particularly `ATL_PROXY_NAME`. Jira
builds every attachment's `content` URL from its own base URL setting, and a
fetch follows that URL verbatim — so a base URL that is right inside the
container and wrong outside it produces attachments that 404 and an issue that
syncs fine. That is a nasty half hour, and it is configuration, not code.

## Task 2 — the workspace, and a credential you do not write

Build `playground/work/11/` with a `sources.yaml` declaring one `jira` source:
`url`, `query`, `user_env`, `token_env`, `deployment`. Copy
`resources/env.sample` to `.env` in the workspace and fill in the two Jira
values.

Do not look at `solution/workspace/sources.yaml` yet. Write it from
`docs/jira-connector.md`, which is the tour of this connector.

Two things to get wrong on purpose, before anything works:

1. Write `token: <your password>` instead of `token_env:`.
2. Restore that, then delete the `token_env:` line and leave `user_env:`.

**Checkpoint.** Both are refused at **load time**, naming the line:

```
sources.yaml, line 30: in 'incidents-jira', 'token' holds a credential, and this
file is committed to git. Name the variable instead, as `token_env: JIRA_TOKEN`,
and set its value in the environment (R1.8).
```

```
sources.yaml, line 9: in 'incidents-jira', `user_env` names a user with no token:
name `token_env` as well
```

The first is R1.8 — `sources.yaml` is committed, so a secret in it is refused by
key name rather than by looking at the value. The second is R1.12: which
`Authorization` header gets sent is decided once, from the keys, and half a
credential is refused here rather than sent as `Basic user:` to a server that
will blame the password.

Now check the third thing, which is a claim you can test:

```bash
dossier run jira-audit --plan
```

**Checkpoint.** It plans without a credential and without touching the network
(R3.8). A token is asked for when a connector is *built*, which only `sync`
does. Unset `DOSSIER_JIRA_TOKEN` and run `dossier sync jira-audit`:

```
source 'incidents-jira' reads its credential from DOSSIER_JIRA_TOKEN, which is
not set. Set DOSSIER_JIRA_TOKEN in the environment, or in `.env` under a
DOSSIER_ name.
```

Exit code 2, before a single request. Then try setting it as `JIRA_TOKEN=` in
`.env` instead — only `DOSSIER_` names are read from that file, and the miss is
reported by name rather than as a 401 (R1.8 row 6, R9.11 row 4).

## Task 3 — put incidents in, and sync them out

```bash
.venv/bin/python playground/11-a-real-jira-on-your-machine/seed_jira.py seed
```

It creates project `PLAY` and four issues from `corpus/incidents/`, the same
notes exercise 01 synced from a folder. Each note's text becomes an issue's
description, written as Jira wiki markup, because a description is wiki markup.
**Only `PLAY-1` carries a file**, and that file is the note exactly as written.

The seed script writes. `dossier` does not, and that separation is deliberate —
put the two side by side and notice that the tool doing the auditing has no verb
for changing what it audits (R1.1).

```bash
cd playground/work/11 && dossier sync jira-audit
```

**Checkpoint.** Five documents, not four. Find both kinds in the ledger:

```
PLAY-1
PLAY-1/postmortem.md
PLAY-2 … PLAY-4
```

`PLAY-1/postmortem.md` is a document in its own right — its own row, its own
snapshot, its own version marker (R1.6). Now work out from `docs/jira-connector.md`
what each marker *is*, and confirm it:

```bash
.venv/bin/python playground/11-a-real-jira-on-your-machine/seed_jira.py show PLAY-1
```

The issue's marker is Jira's `updated`. The file's is the attachment **id** —
not a hash, not a date. Ask yourself why an id is a better marker for a file than
its filename or its timestamp, and what breaks if it is not.

## Task 4 — what was actually held

Find `PLAY-1`'s snapshot under `.dossier/` and read it.

**Checkpoint.** It is the issue JSON as Jira sent it — not re-serialised, not
reformatted, not reduced to the `fields:` projection (R1.2, R2.17). Compare its
size to what `seed_jira.py show` printed: most of a Jira payload is machinery.

Then find `PLAY-1/postmortem.md`'s snapshot and confirm it is the note's bytes,
and that its media type is `text/markdown` — which came from Jira's `mimeType`,
not from the `.md` on the end of the name (R2.16, R8.3). The seed script chose
that type when it uploaded; look at `ATTACHMENT_TYPE` and notice that the media
type of a document is a claim made by the source, which `dossier` believes.

## Task 5 — two kinds of change, and what each one moves

```bash
seed_jira.py touch PLAY-1        # adds a label
dossier sync jira-audit
```

**Checkpoint.** The issue was **re-fetched** — its `updated` moved, so R2.1 had
to look — and a new snapshot was written, because `updated` is *inside* the
projection. Read `sources.yaml`'s comment on `fields:` and work out why it could
not have been otherwise.

That is a finding, not a feature. `normalise` projects onto **top-level** keys,
and a Jira issue keeps everything under one top-level `fields` key. So the
projection is nearly all-or-nothing: it can exclude `self` and `expand` — real,
and worth having, since it means moving this Jira to another hostname does not
re-snapshot every issue — and it cannot exclude `updated`. Write down what you
would propose. `resources/proposal.md` has one answer; yours first.

```bash
seed_jira.py edit PLAY-1         # changes the description
dossier sync jira-audit
```

**Checkpoint.** The sync names `PLAY-1` under its source line with **both**
snapshot addresses, the one it held and the one it holds now, in full (R2.18).
The old snapshot is still there — snapshots are immutable, and a new content
means a new path, never an overwrite (R0.2). Then find the `revisions` table in
the ledger and confirm every address this row has ever held is in it (R2.19).

```bash
seed_jira.py replace-file PLAY-1
dossier sync jira-audit
```

**Checkpoint.** `PLAY-1/postmortem.md` is repointed on its own. Jira has no
"replace": the old attachment was deleted and a new one added, so the filename —
which is the document key — is unchanged while the id, which is the marker,
is not. That pair is what R2.6 turns on, and it is why an attachment carries its
own marker rather than inheriting the issue's.

## Task 6 — a deletion nothing announces

```bash
seed_jira.py delete PLAY-4
dossier sync jira-audit
```

**Checkpoint.** Nothing. `PLAY-4` is still `active` in the ledger, and the sync
is right to leave it there. An incremental listing narrows by
`updated >= "..."`, so an unchanged issue is *also* absent — absence carries no
information, and subtracting held-from-listed against this listing would
tombstone the quiet majority of the source. The connector says so about itself:
`lists_everything = False` (R1.11).

```bash
dossier sync jira-audit --full
```

**Checkpoint.** `PLAY-4` is tombstoned and named (R2.20). `--full` asks the
source for an **unwindowed** listing on demand, so what a narrowing source has
dropped can be tombstoned without editing `fields:` to force a re-evaluation
(R2.22). Then check the thing that makes this safe: `PLAY-1/postmortem.md` was
never at risk in either sync, because `attachments(key)` answers *completely*
for one issue even during an incremental listing — the one place tombstoning
needs no full listing (R2.6 row 3).

Now decide, for your own use: what should run `--full`, and how often? The answer
is not "always", and writing down why is the task.

## Task 7 — what an issue converts to

```bash
dossier convert jira-audit
```

**Checkpoint.** Everything converts:

```
incidents-jira  4 held · 4 converted · 0 cached
```

Four, not five: task 6 tombstoned `PLAY-4`, and a tombstoned document is not
converted. Look at the ledger's `media_type` column to see why the other three
issues converted. Each is `application/vnd.dossier.jira-issue+json`, not
`application/json`: the connector labels an issue with what wrote it (R1.14),
and `jira-issue-markdown`, which ships with `dossier`, claims that pair and
nothing else (R8.16). A converter claiming `application/json` would claim every
JSON document any source ever holds. `PLAY-1/postmortem.md` is still
`text/markdown`, converted by `markdown-text`, because a file an issue carries
is what Jira says it is (R2.16).

Now read `PLAY-1`'s note. The artifacts are under `.dossier/cache/convert/`, and
each has a `.meta.json` beside it naming its converter and the snapshot it was
made from. The ledger's `snapshot_path` column tells you which snapshot `PLAY-1`
holds. Its `content_hash` does not: for an issue, that is the hash of the
`fields:` projection (task 5), and it is not the address of any snapshot.

**Checkpoint.** It opens `# PLAY-1 — Checkout timeouts after the payment gateway
upgrade`. Then comes a line each for status, type, priority, created and
updated, then `**Attachments:** postmortem.md`, then `## Description`. Check
three things against the snapshot you read in task 4:

- The attachment is *named*, not inlined. `postmortem.md` is its own document,
  with its own snapshot (R1.6). If its text were here too, the same sentence
  would sit in two artifacts, and a span found in it could not say which one it
  came from.
- None of the machinery reached the note. Search the snapshot for `avatarUrls`
  and `customfield_`, then search the note for the same strings: neither is
  there (R8.16). Forty kilobytes of that in `{{documents}}` would be forty
  kilobytes a model could find a plausible quote in.
- The description was read as wiki markup and written as markdown. In the
  snapshot it is `*Severity:* major`, `h2. Timeline` and `* 2026-03-02 …`. That
  is how Jira holds a description, and `seed_jira.py` converted each corpus note
  to it when it seeded the issue (`wiki_markup`). In the note it is
  `**Severity:** major`, `## Timeline` and `- 2026-03-02 …`: the corpus note's
  own markdown, back again (R8.17). The summary and the fields are not markup,
  so they are written as typed.

Then read the first proposal in `resources/proposal.md`. It was written when
every issue here was refused as `application/json`. It was accepted in a
different form, and its note says which. Compare it with the section "A Jira
issue" in `specs/008-conversion.md`, and work out which of its arguments
survived.

> **A workspace synced before R1.14** holds its issues as `application/json`.
> `convert` converts the attachments, fails each issue on its own with
> `nothing converts ('application/json', 'markdown')`, and exits 1. The label
> is recorded when an issue is fetched (R2.16), and an
> unchanged issue is not fetched again (R2.1). To force a re-fetch, declare the
> source's `fields:` (`fields: [key, fields]`), or change it if it is already
> declared. That re-fetches every issue (R2.3), and they come back with the
> new label.

## Task 8 — a note of your own

The shipped note is one answer to **which fields are the document**, and the
answer belongs to the workspace, not to `dossier`. This workspace's incidents
carry labels, and the note leaves them out. Suppose a label is something an
auditor here should read.

Write a converter package of your own. It claims the same pair,
`(application/vnd.dossier.jira-issue+json, markdown)`, the way exercise 03's
package claims HTML. It needs `id`, `version`, `media_type`, `kind` and a
`convert` that is a pure function of its payload — no clock, no environment, no
network (R8.1). Put in a field the shipped note leaves out, such as the labels
(the field `seed_jira.py touch` changed in task 5), and keep leaving out the
avatars and the permission ids. The description and comments are wiki markup.
Read them with the library the shipped converter uses, `jira2markdown`, pinned
to the same release. What a library writes goes into the artifact, so moving
the pin is a new version of your converter (R5.4).

Give it an id of its own. `dossier` tells two claims apart by id and version,
and a converter calling itself `jira-issue-markdown` at `1.1.0` would be taken
for the shipped one, listed twice.

```bash
uv pip install -e playground/11-a-real-jira-on-your-machine/solution/dossier_jira_playground
dossier convert jira-audit
```

**Checkpoint.** It converts nothing, the attachment included, even though
neither converter claims the attachment's pair. The refusal names the pair and
both converters, and no document:

```
two converters claim the same pair, and picking either would be picking by installation order:
  (application/vnd.dossier.jira-issue+json, markdown) is claimed by both jira-issue-markdown 1.1.0 and play-jira-issue-markdown 1.0.0
A workspace settles it by naming one under converters: in sources.yaml (R8.13).
```

The winner's id and version go into `K_convert`. If the tie were settled by
installation order, two machines with the same packages would compute
different keys (R5.6). Exercise 03 ran into the same refusal. The workspace
settles it by writing the decision down. Add this line to the top of
`sources.yaml`, beside `sources:`, using your own converter's id if you wrote
one:

```yaml
converters: [play-jira-issue-markdown]
```

Convert again.

**Checkpoint.** `4 held · 3 converted · 1 cached`. The three issues are new
artifacts, under a new converter's key. The attachment's converter did not
change, so its key did not change either. Read `PLAY-1`'s note again. It now
has a `**Labels:**` line holding the label task 5 added, and otherwise it
matches the shipped note. Then misspell the name once (`play-jira-issue-markdwn`).
It is refused before anything converts, and the message names the converters
that are installed (R8.13 row 4). A name that matches nothing would otherwise
be no choice at all.

Should your package declare itself opt-in, as `docling-markdown` does? An
opt-in converter answers only where a workspace names it, so installing it
changes nothing anywhere else (R8.13). Write down what that would have saved
you, and what it would cost someone who installed it and expected it to answer.

Then start the stub model and run the audit:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
    --replies playground/11-a-real-jira-on-your-machine/resources/replies.json \
    --port 8099 --log /tmp/dossier-calls.jsonl

dossier run jira-audit
dossier run jira-audit          # again
```

**Checkpoint.** `extract: 4 document(s) · 0 from cache · 0 failed`, with no
findings: every span the stub quotes is in the note it names (R6.4). The second
run gives `4 from cache`, and the call log does not grow (R5.5). Open the run's
`manifest.json`. It pins
`play-jira-issue-markdown` and `markdown-text`, but not `jira-issue-markdown`,
which is installed and answered nothing (R8.9).

Compare `pipeline.yaml` with exercise 02's: it is the same file with a different
source id. A pipeline says what to audit, never where the documents came from,
and that is the claim this whole exercise was testing. The choice of converter
went into `sources.yaml` and not the pipeline, because which fields of this
source are the document is a fact about the source.

> **Uninstall the package when you are done.** With it installed, two converters
> claim one pair. Any workspace that names neither refuses to convert, and none
> of the workspaces the test suite builds names either. Leaving it installed
> turns the default suite red, as exercise 03's did until it was opt-in.
> `uv pip uninstall dossier-jira-playground`, then take the `converters:` line
> out of this workspace's `sources.yaml`. A name that no installed package
> provides is refused by every command that plans or converts.

## Task 9 — optional: the wrong deployment, and a 401

Change `deployment: datacenter` to `cloud` and sync.

**Checkpoint.** It fails against `/rest/api/2/search/jql`, which this Jira does
not serve. One key decides which listing route is asked and how it is paged —
offset against `total` for Data Center, `nextPageToken` until `isLast` for Cloud
(R1.13). There is no probing and no fallback.

Then restore it and corrupt `DOSSIER_JIRA_TOKEN`.

**Checkpoint.** One 401, reported with the URL and the status, and the token is
**not** sent again in the other form (R1.12 row 4). Confirm the token appears
nowhere in the message, the ledger or the manifest — `Credential` prints as
`<credential from DOSSIER_JIRA_TOKEN>` and nothing echoes a header (R1.8 row 2).

---

## Done when

- five documents from four issues, and you can say why five;
- a repointed issue, a repointed attachment and a tombstoned issue, each shown
  by a different command, and you can say which one needed `--full` and why;
- a converted issue checked against its snapshot, and you can say what was left
  out and why the attachment is only named;
- a converter of your own for a Jira issue, named under `converters:`, and you
  can say why installing it stopped every document, the attachment included,
  until you named it;
- the package uninstalled and `pytest` green.

## Cleaning up

```bash
docker compose -f playground/11-a-real-jira-on-your-machine/docker-compose.yml down -v
uv pip uninstall dossier-jira-playground
rm -rf playground/work/11
```

`down -v` removes both volumes: the Jira home and the database. The licence is
30 days from when you activated it, not from when the container started, so
bringing it back up later means a fresh wizard on a fresh volume.

**Back to:** [the playground index](../README.md).
