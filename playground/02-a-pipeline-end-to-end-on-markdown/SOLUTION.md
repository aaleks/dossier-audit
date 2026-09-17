# 02 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

Terminal 1, from the repository root — the stub model:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
    --replies playground/02-a-pipeline-end-to-end-on-markdown/resources/replies.json \
    --port 8099 --log /tmp/dossier-calls.jsonl
```

Terminal 2:

```bash
mkdir -p playground/work/02/inbox/incidents
cp -r playground/02-a-pipeline-end-to-end-on-markdown/solution/workspace/. playground/work/02/
cp playground/corpus/incidents/PLAY-100[1-4].md playground/work/02/inbox/incidents/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/02/.env

cd playground/work/02
D=../../../.venv/bin/dossier
$D sync incident-audit
$D convert incident-audit
$D run incident-audit --plan
$D run incident-audit
```

---

## Task 1 — the three files of a step

**`pipelines/incident-audit/prompts/01_extract.md`**

```markdown
Extract the requested fields from the incident note below.

Every non-null value must carry the document key, the page where the document has
pages, and the exact sentence the value came from. If a field is not stated in the
note, return it as null with a reason. Do not infer, and do not guess.

<source_document>{{documents}}</source_document>
```

The `<source_document>` tag is the prompt author's, not dossier's: rendering only
replaces what is inside the braces. That matters when a step has two inputs —
each goes under its own labelled tag, so a model asked to attribute a finding can
say which document it read it in.

**`pipelines/incident-audit/schemas/incident.yaml`** is the four fields, as given
in the exercise. Four kinds, four scorers: an `amount` is compared as a number
after normalising thousands separators, a `date` only in unambiguous forms, an
`enum` and a `reference` as case-folded text. The kind is what picks the scorer,
which is why it is declared rather than inferred from whatever the model returned.

The two deliberate breakages:

```console
$ dossier convert incident-audit      # with {{docs}} in the prompt
pipeline.yaml: step 'extract' declares ['documents'] but its prompt never injects it.
A declared input that no placeholder uses is part of the stage's cache key and reaches
the model not at all.
exit 2
```

Both halves of that sentence are failures, and they are reported separately
because they have different fixes (R3.6). The quiet one is the half you did not
see here: `{{docs}}` is a placeholder nothing fills, so without this check it
would reach the model as six literal characters and the answer that came back
would look entirely plausible.

```console
$ dossier convert incident-audit      # with root_cause: {kind: free_text}
pipeline.yaml: step 'extract': incident.yaml: field 'root_cause' is free_text with no
`judge`, and cannot be scored without one
exit 2
```

There is no default rubric to fall back on. Without one the field could only be
string-compared, which would turn a judged rule into a deterministic one nobody
agreed to (R6.10). Exercise 07 adds it properly.

## Task 2 — convert

```console
$ dossier convert incident-audit
incidents-manual  4 held · 4 converted · 0 cached
cache updated · 4 converted · 0 cached

$ dossier convert incident-audit
incidents-manual  4 held · 0 converted · 4 cached
cache updated · 0 converted · 4 cached
```

The artifacts are under `.dossier/cache/convert/<2>/<2>/<key>`, each with a
`.meta.json` beside it. For `text/markdown` the converter is `markdown-text`,
which decodes UTF-8 and re-encodes — nearly nothing, and not quite nothing: it is
what turns "some bytes" into "text a span can be searched in", and it is where an
undecodable file fails loudly against one document instead of downstream with a
stack trace about a byte.

Conversions live in the **cache**, not under `runs/`, and that is a decision with
a reason: raising a converter's version must make every document re-convert
(R5.4), which only means anything if conversions are otherwise reused across
runs. Exercise 03 does exactly that.

## Task 3 — the plan

```console
$ dossier run incident-audit --plan
incident-audit  4 document(s) · model openai:gpt-5.4-mini
no previous run to compare against
! extract: new
1 of 1 step(s) would run · nothing written
```

Checking that "nothing written" is literally true:

```console
$ before=$(find .dossier runs -type f 2>/dev/null | sort | xargs sha256sum | sha256sum)
$ dossier run incident-audit --plan > /dev/null
$ after=$(find .dossier runs -type f 2>/dev/null | sort | xargs sha256sum | sha256sum)
$ [ "$before" = "$after" ] && echo "nothing on disk changed"
nothing on disk changed
```

R4.6. A plan that wrote a manifest, or warmed a cache, would be a run you did not
ask for — and `--plan` is the command you reach for when you are not sure yet.

## Task 4 — the run

```console
$ dossier run incident-audit
run 20260917T184228Z-385d · /…/playground/work/02/runs/20260917T184228Z-385d/manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed
```

The manifest, trimmed:

```json
{
  "run_id": "20260917T184228Z-385d",
  "started_at": "2026-09-17T18:42:28.…Z",
  "dossier_version": "0.1.0",
  "plan": {
    "pipeline": "incident-audit",
    "pipeline_hash": "5aed764040dfbc0d…",
    "model": "openai:gpt-5.4-mini",
    "steps": [
      {
        "id": "extract",
        "inputs": ["documents"],
        "mode": "per_file",
        "prompt_hash": "b3c909cfe88ac27e…",
        "schema_hash": "387e8655133090ff…",
        "generated_schema_hash": "ab74a2c9281eea27…"
      }
    ],
    "documents": [
      {"key": "PLAY-1001.md", "snapshot": "6bdb8cad3ebd2dcf…", "media_type": "text/markdown"},
      …
    ]
  }
}
```

Three hashes for one step, and they are not redundant:

- `prompt_hash` is the prompt **template**, not the rendered prompt. The rendered
  prompt contains the document, which the input hashes already cover.
- `schema_hash` is the declaration file's own text — so a comment or a rubric
  path moving invalidates the step even though the generated schema is unchanged
  (R6.11).
- `generated_schema_hash` is what the model was actually shown, over canonical
  JSON, so the same schema gives the same bytes on every machine (R6.12).

A document is pinned by its **snapshot hash**. That is what makes a replay a
reproduction rather than a re-read: the file on disk may have moved on, the
snapshot has not.

One stage artifact, and its record:

```console
$ cat .dossier/cache/stage/a4/ef/a4eff980…
{"document":"PLAY-1004.md","fields":[{"field":"loss_amount","value":9900.0,"currency":"CHF",
"reason":null,"confidence":"high","source":{"document":"PLAY-1004.md","span":"recorded a loss
of CHF 9'900 in attributed revenue","page":null}}, …]}

$ cat .dossier/cache/stage/a4/ef/a4eff980….meta.json
{
  "attempts": 1,
  "cache_key": "a4eff980d6ddd7d3…",
  "dossier_version": "0.1.0",
  "generated_schema": {"hash": "ab74a2c9281eea27…"},
  "inputs": [{"hash": "d7c5317a23938586…", "path": "documents/PLAY-1004.md", "role": "documents"}],
  "model": "openai:gpt-5.4-mini",
  "options": {},
  "prompt": {"hash": "b3c909cfe88ac27e…", "path": "prompts/01_extract.md", "role": "prompt"},
  "run_id": "20260917T184228Z-385d",
  "schema": {"hash": "387e8655133090ff…", "path": "schemas/incident.yaml", "role": "schema"},
  "step": "extract"
}
```

`attempts: 1` is the one field here that is about what happened rather than about
what was asked. Exercise 06 makes it 2.

## Task 5 — the second run, and the replay

```console
$ wc -l < /tmp/dossier-calls.jsonl
4
$ dossier run incident-audit
run 20260917T184235Z-0c13 · …
  extract: 4 document(s) · 4 from cache · 0 failed
$ wc -l < /tmp/dossier-calls.jsonl
4
```

Four model calls for the first run, none for the second. That is the claim
`FakeModelClient` makes in the test suite by counting calls, seen from outside:
the same question, keyed the same way, is not asked twice (R5.5).

```console
$ dossier run --replay runs/20260917T184235Z-0c13/
replayed 20260917T184235Z-0c13 · incident-audit
  extract: 4 artifact(s) from cache
4 artifact(s) reproduced · no model calls
```

The manifest is the only input. `pipeline.yaml` is not read — not to check that
it agrees, not to warn that it has changed — because a replay that consulted it
would be reproducing today's configuration rather than the run (R4.7). The same
reasoning is why a replay needs no converter installed and no endpoint
configured: everything it needs is addressed by keys the manifest already holds.

## Task 6 — make the model answer differently

Editing a reply in `replies.json` and running again changes nothing: `4 from
cache`, and the call log does not grow. The model's answer is not in the key; the
question is. Editing `severity` in the stub is editing the answer.

Of the five candidates in the exercise:

| Change | Does the run ask again? | Why |
|---|---|---|
| the prompt template | yes | `prompt_hash` is in the key (R5.2) |
| the field declaration | yes | `schema_hash` is in the key (R6.11) |
| the note itself | yes, for that document | a new snapshot means a new input hash |
| the model identifier in `pipeline.yaml` | yes | the pinned identifier is in the key (R5.3) |
| the URL in `.env` | no | where a model is served is per machine and in no key (R9.2) |

The last row is the one that makes this playground possible at all, and the
fourth has a wrinkle that exercise 09 will show you in `--plan`.

---

## What to take to your own project

- Three files per step, each with one job, and a load-time check that they agree
  with one another before anything is spent.
- One place where field names and kinds are written, with everything else
  generated from it.
- Pin evidence by content hash, key the work by the question, and a replay
  becomes a reproduction rather than a re-run.
