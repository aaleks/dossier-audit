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
committed to git. Name the variable instead, as `token_env: JIRA_TOKEN`, and set its value
in the environment (R1.8).

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

## Task 7 — the wall

**[derived]** The message below is assembled by
`application/convert.py:_resolve_converters` and
`domain/conversion.py:select`. The wording is theirs, run against the converters
installed in this repository; the document keys are this exercise's.

```bash
$ dossier convert jira-audit
4 document(s) have no converter:
  PLAY-1 (application/json): nothing converts ('application/json', 'markdown').
    Claimed pairs: ['(application/pdf, markdown)', '(application/pdf, page_images)',
    '(image/jpeg, page_images)', '(image/png, page_images)',
    '(text/markdown, markdown)', '(text/plain, markdown)'].
    A converter is added by installing a package that declares a dossier.converters
    entry point.
  PLAY-2 (application/json): …
  PLAY-3 (application/json): …
  PLAY-4 (application/json): …
```

Four named, not one. And **five** documents refused, not four — the attachment
converts perfectly well and does not get to, because resolution happens for the
whole source before any conversion runs:

```python
plan = _resolve_converters(documents=documents, kinds=kinds, converters=converters)
```

The docstring says why, and it is a design position rather than an implementation
detail: discovering the gap partway through would leave a source half converted
for a reason that was knowable before any work started.

Note also what the message ends with. It does not say "not supported"; it says a
converter is added by installing a package. The refusal names its own fix (R8.5).

## Task 8 — get past it

`solution/dossier_jira_playground/` claims the pair from outside `dossier`,
through the same entry-point group the shipped converters use (R8.7):

```toml
[project.entry-points."dossier.converters"]
jira-issue-markdown = "dossier_jira_playground.issue_markdown:JiraIssueMarkdownConverter"
```

**[run]** What it produces, for a payload of the shape Jira returns:

```
# PLAY-1 — Checkout timeouts after the payment gateway upgrade

**Status:** Open
**Type:** Task
**Priority:** Medium
**Created:** 2026-09-21T10:15:31.212+0000
**Updated:** 2026-09-21T10:15:33.004+0000
**Attachments:** postmortem.md

## Description

**Severity:** major

## Root cause

The gateway upgrade shipped a connection pool whose idle timeout was 30 seconds.

## Comments

**A. Aleks**

Reverted the pool settings.
```

**[run]** And the three properties that make it a converter rather than a
formatter:

```
determinism (same payload twice):        True
independent of JSON key order:           True
not JSON            -> jira-issue-markdown: the payload is not UTF-8 JSON: …
a JSON array        -> jira-issue-markdown: expected a JSON object, got list
an object, no fields-> jira-issue-markdown: the payload has no `fields` object,
                       so it is not a Jira issue
```

Key-order independence is the one worth dwelling on. A converter that wrote
fields in the order they arrived would produce different bytes for the same
issue depending on how Jira serialised it that day — and the convert key would be
stable while the artifact was not, which is the worst version of this failure
because nothing would ever report it (R8.1, R0.4).

The attachment is **named, never inlined**. Two documents holding the same
sentence would make it impossible to say which one a span was grounded in.

**[shape]** After installing it:

```
$ dossier convert jira-audit
incidents-jira  5 held · 5 converted · 0 cached

$ dossier run jira-audit
extract: 5 document(s) · 0 from cache · 0 failed

$ dossier run jira-audit
extract: 5 document(s) · 5 from cache · 0 failed
```

**[run]** The reply file was checked against the documents it describes, using
`dossier`'s own grounding function rather than a plain substring test:

```
documents: ['PLAY-1', 'PLAY-1/postmortem.md', 'PLAY-2', 'PLAY-3', 'PLAY-4']
every match string hits exactly one document: yes
every span locates in the document it names (locate_span): yes
problems: 0
```

That check found a real mistake worth repeating here: the span
`a recorded loss of CHF 18'400` does **not** appear verbatim in the note — it is
broken across a line. It grounds anyway, because `locate_span` normalises
whitespace before searching (R6.4). A plain `in` test would have rejected a
correct reply file, and a reply file "fixed" to satisfy it would have been wrong.

> **Uninstall when you are done.** `tests/unit/test_R008_1__…` collects every
> *installed* converter, skips any whose media type it has no sample payload for,
> and then asserts that every skip is a named exemption:
>
> ```python
> EXEMPT = {"application/pdf", "image/jpeg"}
> uncovered = {c.media_type for c in INSTALLED if c.media_type not in PAYLOADS}
> assert uncovered <= EXEMPT
> ```
>
> `PAYLOADS` has `text/markdown`, `text/plain` and `image/png`. So
> `application/json` is neither covered nor exempt, and leaving this package
> installed turns the default suite red — exactly as exercise 03's package does,
> and for exactly the reason that guard exists: a converter quietly exempted from
> the purity check is the one outcome nobody would notice.
>
> ```bash
> uv pip uninstall dossier-jira-playground
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
