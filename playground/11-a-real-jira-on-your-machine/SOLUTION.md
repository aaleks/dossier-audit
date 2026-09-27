# 11 · Solution

**This file is not like the other solutions in this playground, and you should
know how before you trust a line of it.**

Every other `SOLUTION.md` here opens by saying that each command was run against
this repository and the output shown is the output it produced. That promise
cannot be made about a Jira Data Center: it needs a licence issued to a person,
and a run of it is not reproducible anyway — Jira assigns its own issue keys and
stamps `updated` from its own clock, so no snapshot hash, ledger row or cache key
in a live run would match one printed here.

So every block below is marked:

| Mark | Means |
|---|---|
| **[run]** | Run against this repository. The output is what it produced. |
| **[derived]** | Rendered from the code path that produces it, with the values a live run would fill in. The wording is the code's; the keys are the example's. |
| **[shape]** | What to expect, and what to check. Not a transcript. |

Where something depends on your instance rather than on `dossier`, it says so
instead of guessing.

---

## Task 1 — bring Jira up

**[run]** The compose file is valid and both images are pinned to tags that
exist:

```bash
$ docker compose -f playground/11-a-real-jira-on-your-machine/docker-compose.yml config >/dev/null && echo ok
ok
$ docker manifest inspect atlassian/jira-software:10.3.23 >/dev/null && echo ok
ok
$ docker manifest inspect postgres:16.6-alpine >/dev/null && echo ok
ok
```

**[shape]** Booting takes three to five minutes the first time. `seed_jira.py
wait` polls `/status` and prints each state it sees:

```
  FIRST_RUN ...
Jira is RUNNING at http://localhost:8080
```

`FIRST_RUN` means the port is answering and the wizard is unfinished. Nothing in
this exercise can finish it for you — it needs a licence key, and the licence
step is a person with an Atlassian account.

The one setting worth understanding rather than copying is `ATL_PROXY_NAME`.
Jira builds the `content` URL of every attachment from its own base URL, and
`JiraConnector.fetch` follows that URL exactly as given:

```python
attachment = self._attachment(item, filename)
response = self._get(attachment["content"])
```

So if Jira thinks it lives at `http://jira:8080`, the issues sync and every
attachment fetch fails from outside the container. That is configuration
producing a failure that reads like a bug.

## Task 2 — the workspace, and a credential you do not write

`solution/workspace/sources.yaml` is the finished file, and its comments are
half the exercise. The part that matters:

```yaml
sources:
  - id: incidents-jira
    type: jira
    url: http://localhost:8080
    query: project = PLAY
    user_env: DOSSIER_JIRA_USER
    token_env: DOSSIER_JIRA_TOKEN
    deployment: datacenter
    fields: [key, fields]
```

The finished file also has `converters: [play-jira-issue-markdown]` at the top.
That line belongs to task 8, and it needs task 8's package installed: every
command that plans or converts refuses a name no installed package provides
(R8.13). Until then, leave it out.

`query` has **no `ORDER BY`**, and that is not style. The connector narrows an
incremental listing by appending a clause (R1.4):

```python
jql = self._query if since is None else f"{self._query} AND {_updated_since(since)}"
```

`project = PLAY ORDER BY created ASC AND updated >= "..."` is not JQL, and the
error comes back from Jira as a parse failure with no hint that `dossier`
assembled it.

**[run]** The two deliberate mistakes, both refused at load time:

```bash
$ dossier run jira-audit --plan        # with `token: hunter2` in place of token_env
sources.yaml, line 30: in 'incidents-jira', 'token' holds a credential, and this file is
committed to git. Name the variable instead, as `token_env: DOSSIER_JIRA_TOKEN`, and set its
value in the environment (R1.8).

$ dossier run jira-audit --plan        # with token_env removed, user_env kept
sources.yaml, line 9: in 'incidents-jira', `user_env` names a user with no token: name
`token_env` as well
```

The first is refused **by key name**. Nothing looked at `hunter2` to decide it
was a secret — `JiraKeys` is `extra="forbid"` and `token` is a name that is
refused where it is read, so the check works on a value nobody has seen yet.

**[run]** Planning needs no credential, and makes no request (R3.8):

```bash
$ dossier run jira-audit --plan
jira-audit  0 document(s) · model openai:gpt-5.4-mini
no previous run to compare against
! extract: new
1 of 1 step(s) would run · nothing written
```

Zero documents because nothing has synced yet. A plan resolves configuration;
only `sync` builds a connector.

**[run]** And syncing without the named variable set stops before any request:

```bash
$ dossier sync jira-audit
source 'incidents-jira' reads its credential from DOSSIER_JIRA_TOKEN, which is not set.
Set DOSSIER_JIRA_TOKEN in the environment, or in `.env` under a DOSSIER_ name.
$ echo $?
2
```

Note what the message names: the **variable**, not the source's URL and not a
status code. The failure is in your `.env`, and it says so.

## Task 3 — put incidents in, and sync them out

**[shape]**

```bash
$ seed_jira.py seed
created project PLAY (Playground Incidents)
issue type: Task
created PLAY-1  Checkout timeouts after the payment gateway upgrade  + postmortem.md
created PLAY-2  Nightly export missed the reporting window
created PLAY-3  Warehouse terminals offline after a firewall rule change
created PLAY-4  Search latency spike during the spring campaign

Seeded: four issues, one of them carrying a file. That is five
documents -- PLAY-1 .. PLAY-4 and
`PLAY-1/postmortem.md`, which is its own address (R1.6).
```

**Your keys may differ.** `PLAY-1` is what an empty Jira issues first; a project
that had already numbered issues continues from where it was. Everything below
uses `PLAY-1`, and if yours are `PLAY-17..20` then the `match` and `document`
values in `resources/replies.json` need renumbering to match. Nothing about this
is `dossier`'s doing — the key belongs to the source, which is the first real
difference from a folder, where the key was a filename you chose.

The description is not the note's markdown. `wiki_markup` writes the constructs
the notes use as Jira wiki markup: `h2. Impact`, `*Severity:*`, and `* item`
with its wrapped lines joined. Jira holds a description in that form, and
`dossier` reads it that way (R8.17). Posted as markdown, `**Severity:** major`
would be read as emphasis wrapped in stars and come back `***Severity:***
major`. Task 7 shows the note coming back as markdown.

`issue_type` is asked rather than assumed:

```python
response = http.get("/rest/api/2/issue/createmeta", params={"projectKeys": PROJECT_KEY})
```

Which issue types a project has depends on the template it was created from. A
hard-coded `"Task"` is the kind of thing that works on the instance it was
written against and nowhere else.

**[shape]** The sync, and the number to notice:

```
incidents-jira
  5 new · 5 fetched · 5 written
```

Five, from four issues. `PLAY-1/postmortem.md` is a document, not a property of
`PLAY-1`. In `application/sync.py` the two are built as targets side by side:

```python
for target in (
    _Target(ref.key, ref.remote_version, config.fields, True),
    *(_Target(a.key, a.remote_version, None, False, ref.key) for a in attached),
):
```

Two things are visible in that expression and worth stopping on. The attachment's
projection is `None` — a file's bytes are hashed as received, because a
projection needs a JSON object and a PDF is not one. And `attachments(ref.key)`
is called for **every listed issue**, changed or not, because an issue's version
marker says nothing about the file hanging off it.

**[shape]** `seed_jira.py show PLAY-1` prints the two markers:

```json
{
  "key": "PLAY-1",
  "fields": {
    "summary": "Checkout timeouts after the payment gateway upgrade",
    "updated": "2026-09-21T10:15:33.004+0000",
    "attachment": [
      {
        "id": "10000",
        "filename": "postmortem.md",
        "mimeType": "text/markdown",
        "content": "http://localhost:8080/secure/attachment/10000/postmortem.md"
      }
    ]
  }
}
```

The issue's marker is `updated`. The file's is `id`. An id is the better marker
because Jira has no replace: a new file is a new id, so the id moves exactly when
the bytes do — while a timestamp can move for a rename and a filename does not
move at all.

And when `updated` is missing, the marker is `None` and never a fetch time:

```python
return str(updated) if updated else None
```

A fabricated marker would make R2.1 skip an item that really did change, and
nothing downstream could detect it (R1.5).

## Task 4 — what was actually held

**[shape]** `PLAY-1`'s snapshot is the issue JSON **as Jira sent it** — one line,
unformatted, with every `self` URL and avatar map still in it. It is not the
`fields: [key, fields]` projection, and it is not re-serialised.

That is two rules meeting. The payload is stored byte for byte (R1.2), because
re-serialising would change the content hash of every issue for a reason nobody
could find afterwards. And the projection decides only what the hash is computed
*over*, never what is kept (R2.17):

```python
# domain/sync.py
"""The stored snapshot is always the raw payload. This exists only to decide
what the content hash is computed over."""
```

`PLAY-1/postmortem.md`'s snapshot is the note's bytes, at `text/markdown` — and
that type came from Jira, not from the filename:

```python
media_type=reported_media_type(
    attachment.get("mimeType"), response.headers.get("content-type")
),
```

What the source records wins over what the transport said, and either wins over a
guess at the extension (R2.16, R8.3). In this exercise the seed script chose that
type when it uploaded the file — `ATTACHMENT_TYPE = "text/markdown"` — so you can
see the whole chain from the decision to the ledger row.

## Task 5 — two kinds of change, and what each one moves

**[shape]** `touch` adds a label. `updated` moves, so R2.1 re-fetches; and
because `updated` sits *inside* the projection, the hash moves too and a new
snapshot is written for a document whose content nobody changed.

This is the finding the task is really about. `normalise` projects onto
**top-level** keys only:

```python
projected = {name: document[name] for name in sorted(fields) if name in document}
```

A Jira issue's top level is `expand`, `id`, `self`, `key`, `fields` — and
everything a person would call content, `updated` included, is nested under
`fields`. So `fields: [key, fields]` buys exactly one thing: `self` and `expand`
stop being content, which means moving this Jira to another hostname or upgrading
it no longer re-snapshots every issue. It buys nothing finer, and there is no
`fields: [fields.summary]`.

The alternative is worse, which is what makes this a real trade rather than an
oversight: `fields: [key]` would make a genuine edit to the description invisible,
and that is the failure R2.10 exists to prevent.

`resources/proposal.md` writes this up as a proposal for dotted paths, including
the part that argues against it — arrays turn a YAML key into a path language.
Write yours before reading it.

**[shape]** `edit` changes the description. Both the marker and the projection
move, and the sync says so in full (R2.18):

```
incidents-jira
  repointed PLAY-1
    was  sha256:9c1f…  (64 hex characters, in full)
    now  sha256:04ab…
```

Both addresses, complete. The previous snapshot still exists — a new content is a
new content-addressed path, never an overwrite (R0.2) — so "what did this
document say last week" is answerable by reading, not by inference. The
`revisions` table keeps every address the row has ever held, append-only, seeded
from `items` for a ledger written before it existed (R2.19).

**[shape]** `replace-file` deletes the attachment and uploads new bytes under the
same name. `PLAY-1/postmortem.md` is repointed **on its own**: the key is the
filename and did not change; the marker is the id and did. That is R2.6, and it
is the reason an attachment carries its own marker instead of inheriting the
issue's.

On a real Jira the issue's `updated` also moves when an attachment changes, so
you will see the issue re-fetched as well. That does not weaken the point — it
sharpens it. The two documents are settled independently, by their own markers,
and you can see that in the ledger even when Jira touches both.

## Task 6 — a deletion nothing announces

**[shape]** After `seed_jira.py delete PLAY-4`:

```bash
$ dossier sync jira-audit
incidents-jira
  0 changed · 0 new · 0 fetched
```

`PLAY-4` is still `active`, and that is correct. The listing was narrowed by
`updated >= "..."`, so an *unchanged* issue is absent from it too. Absence
carries no information here, and subtracting held-from-listed would tombstone
the quiet majority of the source. The connector declares this about itself, at
the top of the class:

```python
lists_everything = False
```

```bash
$ dossier sync jira-audit --full
incidents-jira
  tombstoned PLAY-4
```

`--full` asks the source for an unwindowed listing on demand, so a deletion can
be found without editing `fields:` to force a re-evaluation of everything
(R2.22). Two things are worth checking rather than believing:

- `PLAY-1/postmortem.md` was never at risk in either sync. `_settle_attachments`
  works from `attachments(key)`, which answers *completely* for one issue even
  during an incremental listing — the one place tombstoning needs no full
  listing (R2.6 row 3).
- A tombstone is a state, not a delete. The row and its snapshots are still
  there; what changed is that the document is no longer active.

## Task 7 — what an issue converts to

**[derived]** Every console block in this task and the next was produced by the
real `dossier` CLI. It was run through tasks 3 to 6 and then these two, against a
Jira played by a local HTTP server. That server answered the three routes the
connector asks with `PLAY-1` to `PLAY-4`: the seeded summaries and descriptions,
wrapped in the payload of `tests/fixtures/jira/INC-4821.json`, a Jira Server
issue with its avatars and custom fields. The wording is `dossier`'s. The
timestamps, the status, the type and the priority come from the played Jira,
and yours will be your instance's.

```console
$ dossier convert jira-audit
incidents-jira  4 held · 4 converted · 0 cached
cache updated · 4 converted · 0 cached
```

Four held, not five, because task 6 tombstoned `PLAY-4`, and `convert` reads
only the rows that are not tombstoned. The ledger shows what each document is
held as:

```console
$ python -c "import sqlite3; [print(*r) for r in sqlite3.connect('.dossier/ledger.db').execute('select key, media_type, state from items order by key')]"
PLAY-1 application/vnd.dossier.jira-issue+json active
PLAY-1/postmortem.md text/markdown active
PLAY-2 application/vnd.dossier.jira-issue+json active
PLAY-3 application/vnd.dossier.jira-issue+json active
PLAY-4 application/vnd.dossier.jira-issue+json tombstoned
```

An issue is labelled by what wrote it, and the connector says so where it
fetches one (R1.14):

```python
response = self._get(f"{self._base}{ISSUES}/{item}")
return RawItem(
    key=key,
    payload=response.content,
    media_type=JIRA_ISSUE,
    remote_version=_version_of(response.json()),
)
```

R1.14 gives the reason: a converter claiming `application/json` would claim
every JSON document any source ever holds, whether a webhook body, a
configuration export or a Confluence page, and read each one as though Jira had
written it. `jira-issue-markdown` claims the Jira type and nothing else. Spec
008 says it ships with the connector "because a connector whose documents
nothing reads is half a source". The attachment is still labelled by what Jira
says it is (R2.16), and `markdown-text` converts it.

Which artifact is `PLAY-1`'s? A `.meta.json` names the snapshot an artifact was
made from, and the ledger's `snapshot_path` ends in the snapshot's address:

```console
$ python - <<'PY'
import json, pathlib, sqlite3
held = {path.rsplit("/", 1)[-1]: key for key, path in
        sqlite3.connect(".dossier/ledger.db").execute("select key, snapshot_path from items")}
for meta in sorted(pathlib.Path(".dossier/cache/convert").rglob("*.meta.json")):
    m = json.loads(meta.read_text(encoding="utf-8"))
    print(f"{held[m['snapshot']]:22} {m['converter_id']:20} {meta.as_posix()[:-len('.meta.json')]}")
PY
PLAY-1/postmortem.md   markdown-text        .dossier/cache/convert/11/2b/112b55ff…
PLAY-1                 jira-issue-markdown  .dossier/cache/convert/16/4c/164c01f2…
PLAY-2                 jira-issue-markdown  .dossier/cache/convert/23/ba/23ba6114…
PLAY-3                 jira-issue-markdown  .dossier/cache/convert/29/51/2951ff22…
```

The ledger's `content_hash` would not work here. For an issue it is the hash of
the `fields: [key, fields]` projection, which is not the address of any
snapshot (R2.17). For a folder source the two are the same, which is why
exercise 03's version of this script could use it.

```console
$ cat .dossier/cache/convert/16/4c/164c01f2…
# PLAY-1 — Checkout timeouts after the payment gateway upgrade

**Status:** Open
**Type:** Task
**Priority:** Medium
**Created:** 2026-09-21T10:15:31.212+0000
**Updated:** 2026-09-21T11:06:30.905+0000
**Attachments:** postmortem.md

## Description

**Severity:** major
**Resolved:** 2026-03-04
**Systems affected:** checkout-api, payments-gateway

## Timeline

- 2026-03-02 09:14 UTC — checkout starts returning 504s on about one request in five. The on-call engineer is paged by the synthetic checkout probe.
…

## Impact

Finance reconciled 214 abandoned baskets against the gateway's own records, a
recorded loss of CHF 18'400.

## Follow-up

- Align pool and balancer timeouts in the shared service template.
- Add a synthetic probe that fails on a closed-socket retry rather than on a 504.

## Correction

Finance restated the recorded loss after reconciliation.
```

There is no `Resolution` line because the issue has none, and no `## Comments`
because the seeded issues have no comments (R8.16). The `## Correction` is task
5's `edit`.

The three checks:

- **The attachment is named, never inlined.** `**Attachments:** postmortem.md`,
  and none of its text. It is its own document (R1.6): the same sentence in two
  artifacts is a span that cannot say which one it was found in.
- **No machinery reached the note.**

  ```console
  $ for w in avatarUrls customfield_; do echo "$w  snapshot $(grep -o $w .dossier/snapshots/5f/00/5f0083a4… | wc -l)  note $(grep -o $w .dossier/cache/convert/16/4c/164c01f2… | wc -l)"; done
  avatarUrls  snapshot 5  note 0
  customfield_  snapshot 93  note 0
  ```

  A 9 KB payload became a 1.5 KB note. The played payload is a Jira Server
  issue with 93 custom fields. How many yours has depends on your instance, and
  the note holds none of them either way.
- **The description was read as wiki markup and written as markdown.** The
  snapshot holds what `seed_jira.py` posted:

  ```console
  $ python -c "import json; print(*json.load(open('.dossier/snapshots/5f/00/5f0083a4…', encoding='utf-8'))['fields']['description'].splitlines()[:7], sep='\n')"
  *Severity:* major
  *Resolved:* 2026-03-04
  *Systems affected:* checkout-api, payments-gateway

  h2. Timeline

  * 2026-03-02 09:14 UTC — checkout starts returning 504s on about one request in five. The on-call engineer is paged by the synthetic checkout probe.
  ```

  REST API version 2 returns a description as wiki markup on both Cloud and Data
  Center, and `jira-issue-markdown` hands it to `jira2markdown` (R8.17). What
  comes back is the corpus note's own markdown. Apart from the list items, which
  the seed joined onto one line, it is the note byte for byte. Had the seed
  posted the markdown as it stood, the same converter would have read
  `**Severity:**` as wiki emphasis wrapped in stars and written
  `***Severity:***`.

**[derived]** A workspace synced before R1.14 still holds its issues as
`application/json`, with its attachment already converted. The output below was
produced after R8.25 by a folder source holding the same media types, three
`application/json` payloads and one `text/markdown` file, named for the issues
they stand for. The source declares no `convert:`, as this workspace's does not:

```console
$ dossier convert jira-audit
incidents-jira  4 held · 0 converted · 1 cached · 3 failed
    PLAY-1: nothing converts ('application/json', 'markdown'). Claimed pairs: ['(application/pdf, markdown)', '(application/pdf, page_images)', '(application/vnd.dossier.confluence-page+json, markdown)', '(application/vnd.dossier.jira-issue+json, markdown)', '(image/jpeg, page_images)', '(image/png, page_images)', '(text/csv, markdown)', '(text/html, markdown)', '(text/markdown, markdown)', '(text/plain, markdown)']. A converter is added by installing a package that declares a dossier.converters entry point.
    PLAY-2: nothing converts ('application/json', 'markdown'). …
    PLAY-3: nothing converts ('application/json', 'markdown'). …
cache updated · 0 converted · 1 cached
$ echo $?
1
```

Each issue fails on its own and the attachment is served from cache, because
nothing here declared a kind: `markdown` was `dossier`'s default for
`application/json` (R8.10), and a default pair nothing claims fails its own
document (R8.25). Before R8.25 the same three issues stopped the source, and the
attachment was not converted either.

The message reads as though a converter were missing, but none is. A label is
recorded when an issue is fetched (R2.16), and an unchanged issue is not fetched
again (R2.1). Changing `fields:` changes the source's configuration hash, which
re-fetches every issue (R2.3):

```console
$ # fields: [key, fields] changed to fields: [key, fields, id]
$ dossier sync jira-audit
incidents-jira  4 known · 3 changed · 0 new -> 3 fetched
…
```

The three issues are fetched again and recorded under the new label, and
`convert` then reads them as it did above. `id` was added only because it was a
change to make. Declaring `fields: [key, fields]` where no `fields:` was
declared before has the same effect.

`resources/proposal.md` is the proposal this task used to end in, written when
every issue was refused. It is kept as it was written, with a note at the top
saying how it was settled. Its first half argued that a converter claiming
`application/json` claims every JSON document, and that argument landed almost
word for word in R1.14. What changed is the answer. The proposal was that
`dossier` should claim nothing, and add a note under R8.5. What landed was a
media type that only a Jira issue carries, so `dossier` could ship a converter
claiming it without claiming anyone else's JSON.

## Task 8 — a note of your own

`solution/dossier_jira_playground/` claims the same pair from outside `dossier`,
through the entry-point group the shipped converters use (R8.7):

```toml
[project.entry-points."dossier.converters"]
play-jira-issue-markdown = "dossier_jira_playground.issue_markdown:JiraIssueMarkdownConverter"
```

The difference that matters is one decision about which fields are the
document: **the labels are part of it**, sorted, on a line of their own,
because a label set has no order that Jira means anything by. Everything else
matches the shipped note, and its docstring says why:

- The description and comments are read as wiki markup with `jira2markdown`,
  the same way (R8.17). The package depends on the release `dossier` pins,
  `jira2markdown==0.5.1`, so installing it changes nothing already installed.
  It pins exactly, because what the library writes is inside the artifact, and
  the convert key names this converter's version, not the library's (R5.4).
- It writes less of a comment than the shipped note: the author, not the time,
  and nothing when `comment.total` says the payload holds fewer comments than
  there are (R8.18). The seeded issues have no comments. A Jira whose threads
  matter wants the shipped note.

Its id is `play-jira-issue-markdown`, not `jira-issue-markdown`. `claims` in
`domain/conversion.py` treats two converters with the same id and version as
"one claim made through two entry-point paths, which is untidy rather than
ambiguous". A copy that kept the shipped id and version would be taken for the
shipped converter, and which of the two wrote an artifact would then turn on
installation order, under a convert key saying it made no difference.

**[run]** The three properties that make it a converter rather than a formatter,
plus the one it adds:

```
determinism (same payload twice):        True
independent of JSON key order:           True
independent of label order:              True
not JSON            -> play-jira-issue-markdown: the payload is not UTF-8 JSON: …
a JSON array        -> play-jira-issue-markdown: expected a JSON object, got list
an object, no fields-> play-jira-issue-markdown: the payload has no `fields` object,
                       so it is not a Jira issue
```

Key-order independence is the one worth dwelling on. A converter that wrote
fields in the order they arrived would produce different bytes for the same
issue depending on how Jira serialised it that day — and the convert key would be
stable while the artifact was not, which is the worst version of this failure
because nothing would ever report it (R8.1, R0.4).

**[run]** Installed, with nothing named. The refusal depends on what is
installed and on no document, so it was produced with this package installed
beside `dossier` and a workspace that names neither converter:

```console
$ dossier convert jira-audit
two converters claim the same pair, and picking either would be picking by installation order:
  (application/vnd.dossier.jira-issue+json, markdown) is claimed by both jira-issue-markdown 1.1.0 and play-jira-issue-markdown 1.0.0
A workspace settles it by naming one under converters: in sources.yaml (R8.13).
$ echo $?
2
```

Nothing converts, `PLAY-1/postmortem.md` included, and neither converter claims
`text/markdown`. No document is named because none is at fault: two answers for
one pair is an installation to settle, and it is refused once, as that (R8.24
row 5). `claims` in `domain/conversion.py` is asked about every installed claim
before any document is resolved, so a tie anywhere stops the run. Exercise 03's
task 2 ran into the same refusal, and so do the repository's tests (see below).

`solution/workspace/sources.yaml` settles it, beside `sources:` rather than
inside the source:

```yaml
converters: [play-jira-issue-markdown]
```

The reason it sits there is in spec 008: a manifest pins one converter per pair
(R8.9), and a replay recomposes every conversion from that pin (R4.7). One
converter per pair per workspace keeps both of those true.

```console
$ dossier convert jira-audit        # converters: [play-jira-issue-markdwn]
sources.yaml names play-jira-issue-markdwn under converters:, and no installed package provides it. Installed: docling-markdown, jira-issue-markdown, jpeg-pages, markdown-text, pdf-images, pdf-markdown, play-jira-issue-markdown, png-pages, text-plain. A converter is added by installing a package that declares a dossier.converters entry point.

$ dossier convert jira-audit        # converters: [play-jira-issue-markdown]
incidents-jira  4 held · 3 converted · 1 cached
cache updated · 3 converted · 1 cached
```

Three issues are converted, under a key that now names
`play-jira-issue-markdown`. The attachment is cached, because its converter,
and therefore its key, did not change. `PLAY-1`'s new note:

```
# PLAY-1 — Checkout timeouts after the payment gateway upgrade

**Status:** Open
**Type:** Task
**Priority:** Medium
**Created:** 2026-09-21T10:15:31.212+0000
**Updated:** 2026-09-21T11:06:30.905+0000
**Labels:** touched-1790500000
**Attachments:** postmortem.md

## Description

**Severity:** major
**Resolved:** 2026-03-04
**Systems affected:** checkout-api, payments-gateway

## Timeline
…
```

The only line that differs from the shipped note is `**Labels:**`. Its value is
task 5's `touch`, spelt the way the played Jira spelt it. Yours carries the epoch
second at which you ran it.

```console
$ dossier run jira-audit
run 20260925T054748Z-411e · …/runs/20260925T054748Z-411e/manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · tokens not reported

$ dossier run jira-audit
run 20260925T054749Z-ef42 · …/runs/20260925T054749Z-ef42/manifest.json
  extract: 4 document(s) · 4 from cache · 0 failed

$ wc -l < /tmp/dossier-calls.jsonl
4
```

There are four calls, one per document, and the second run makes none (R5.5).
There are no findings: every span the stub quotes is in the document it names.
The manifest pins what answered, and not what was installed (R8.9):

```json
"converters": [
  {"id": "play-jira-issue-markdown", "version": "1.0.0",
   "media_type": "application/vnd.dossier.jira-issue+json", "kind": "markdown"},
  {"id": "markdown-text", "version": "1.0.0",
   "media_type": "text/markdown", "kind": "markdown"}
]
```

**[run]** The reply file was checked against the notes each converter writes
for all five documents. The descriptions are the ones `seed_jira.py` posts, and
the check uses `dossier`'s own grounding function rather than a plain substring
test:

```
jira-issue-markdown        spans 19  ungrounded 0  every match hits exactly one document
play-jira-issue-markdown   spans 19  ungrounded 0  every match hits exactly one document
```

That check still finds the mistake worth repeating here. The span
`a recorded loss of CHF 18'400` does **not** appear verbatim in either note,
because it is broken across a line. It grounds anyway, because `locate_span`
normalises whitespace before searching (R6.4). A plain `in` test would have
rejected a correct reply file, and a reply file "fixed" to satisfy it would have
been wrong.

> **Uninstall when you are done.** The R8.1 purity rows pass with this package
> installed: the suite carries a sample Jira issue, so `play-jira-issue-markdown`
> is checked like any other converter. What fails is everything that converts.
> None of the suite's workspaces names either Jira converter, and with two
> claimants for one pair each of them refuses before anything converts:
>
> ```
> AssertionError: two converters claim the same pair, and picking either would be picking by installation order:
>     (application/vnd.dossier.jira-issue+json, markdown) is claimed by both jira-issue-markdown 1.1.0 and play-jira-issue-markdown 1.0.0
>   A workspace settles it by naming one under converters: in sources.yaml (R8.13).
> ```
>
> The workspaces those tests build hold notes in a folder, such as
> `INC-4821.md`, which have nothing to do with Jira. That is the
> refusal doing its job: a converter installed into an environment decides for
> every workspace in it that does not decide for itself.
>
> ```bash
> uv pip uninstall dossier-jira-playground
> ```
>
> Then take `converters: [play-jira-issue-markdown]` out of the workspace's
> `sources.yaml`. With the package gone, it is a name that no installed package
> provides, and `run --plan` refuses it as `convert` does:
>
> ```
> sources.yaml names play-jira-issue-markdown under converters:, and no installed package provides it. Installed: docling-markdown, jira-issue-markdown, jpeg-pages, markdown-text, pdf-images, pdf-markdown, png-pages, text-plain. A converter is added by installing a package that declares a dossier.converters entry point.
> ```

## Task 9 — optional: the wrong deployment, and a 401

**[shape]** `deployment: cloud` against this Data Center asks a route it does not
serve:

```
GET http://localhost:8080/rest/api/2/search/jql answered 404 Not Found
```

One key decides both the route and the paging strategy, and there is no probing:

```python
pages = self._cloud_pages(jql) if self._deployment == "cloud" else self._pages(jql)
```

Data Center pages `/rest/api/2/search` by offset until `total`; Cloud pages
`/rest/api/2/search/jql` by the token each page hands back until `isLast` (R1.13).

**[shape]** A wrong token:

```
GET http://localhost:8080/rest/api/2/search answered 401 Unauthorized
```

Once. The header was decided from the keys before the first request:

```python
if not token:
    return None
if user:
    return f"Basic {pair}"
return f"Bearer {token}"
```

`user_env` is set, so it was Basic, and a 401 does not make it try Bearer. A
probe-and-fall-back would send your credential to the server a second time in
another form, and would turn "your password is wrong" into "something about auth
failed" (R1.12 row 4).

The token is in none of it. `JiraRequestFailed` names the method, the URL and the
status, and `Credential` prints as `<credential from DOSSIER_JIRA_TOKEN>`.

---

## What this exercise was actually testing

`pipelines/jira-audit/pipeline.yaml` is exercise 02's pipeline with one word
changed — the source id. The prompt and the field declaration are copied from
exercise 02 unmodified. Swapping a folder of markdown for an authenticated,
paginated, remote Jira with attachments changed `sources.yaml` and nothing else.

That is the claim worth having checked yourself, because it is the one that
decides whether any of the rest of this is worth it.

**Back to:** [the playground index](../README.md).
