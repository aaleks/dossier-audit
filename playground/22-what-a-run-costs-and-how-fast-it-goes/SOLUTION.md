# 22 · Solution

Every command below was run against this repository, in order and in one pass,
on 2026-10-02, against the stub and, for task 7, a local MLflow 3 server. The
output shown is the output it produced. The workspace's absolute path is cut
from the `run` lines, and the run ids and timings are that pass's. Yours will
differ.

## Run the prepared answer

Terminal 1:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/22-what-a-run-costs-and-how-fast-it-goes/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl --usage
```

Terminal 2:

```bash
E=playground/22-what-a-run-costs-and-how-fast-it-goes
mkdir -p playground/work/22/inbox/incidents
cp -r $E/solution/workspace/. playground/work/22/
cp playground/corpus/incidents/*.md playground/work/22/inbox/incidents/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/22/.env

cd playground/work/22
D=../../../.venv/bin/dossier
$D sync incident-review && $D run incident-review
```

To see which model each call named, one line per call:

```bash
python -c "import json; [print(json.loads(l)['model'], json.loads(l)['documents']) for l in open('/tmp/dossier-calls.jsonl')]"
```

---

## Task 1 — two steps, two models

```yaml
# pipelines/incident-review/pipeline.yaml
sources: [incidents]

model: openai:gpt-5.4-mini

steps:
  - id: extract
    prompt: prompts/01_extract.md
    input: documents
    mode: per_file
    output: schemas/incident.yaml

  - id: summary
    prompt: prompts/02_summary.md
    input: extract
    mode: aggregate
    model: openai:gpt-5.4
```

`01_extract.md` and `schemas/incident.yaml` are exercise 02's, unchanged.
`02_summary.md` asks for three sentences from `<extractions>{{extract}}</extractions>`.
`summary` has no `output`, so its answer is kept as text, under
`runs/<id>/summary/aggregate.md`.

```console
$ dossier sync incident-review
incidents  0 known · 0 changed · 4 new -> 4 fetched
ledger updated · 4 new snapshots · 0 tombstoned

$ dossier run incident-review --plan
incident-review  4 document(s) · model openai:gpt-5.4-mini
no previous run to compare against
! extract: new
! summary: new
      model: openai:gpt-5.4
2 of 2 step(s) would run · nothing written
```

The first line names the pipeline's model, which every step asks with unless
it names its own. So the plan names a model under a step only where the step
names one (R3.14).

## Task 2 — one run, two models

```console
$ dossier run incident-review
run 20261002T062444Z-07b1 · runs/20261002T062444Z-07b1/manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · 1,573 tokens in · 644 out
  summary: 1 document(s) · 0 from cache · 0 failed · 1,285 tokens in · 61 out
```

The call log, one line per call:

```
gpt-5.4-mini ['PLAY-1001.md']
gpt-5.4-mini ['PLAY-1002.md']
gpt-5.4-mini ['PLAY-1003.md']
gpt-5.4-mini ['PLAY-1004.md']
gpt-5.4 ['PLAY-1001.md', 'PLAY-1002.md', 'PLAY-1003.md', 'PLAY-1004.md']
```

The model is named as its provider names it, without `openai:` (R9.12). In
the manifest's plan:

```
pipeline openai:gpt-5.4-mini
extract  (no model)
summary  openai:gpt-5.4
```

- **Why `summary` costs so much input.** Its prompt holds all four extractions,
  every field with its value, its span and its reason. One `aggregate` call
  reads what four `per_file` calls wrote, so it is where a stronger model is
  worth paying for, and also where the input is largest.
- **Naming the pipeline's own model** changes nothing (R3.14 row 7). If it did,
  writing out a default would re-run a step for no reason, and two pipelines
  meaning the same thing would not share a cache.
- **The judge** is the pipeline's `model:` (R3.14 row 11). A step's own model
  answers that step, and judges nothing.

## Task 3 — a name that moves

```console
$ dossier run incident-review --plan          # summary: model: openai:gpt-4o
pipeline.yaml, line 22: steps.1.model model 'openai:gpt-4o' is a name OpenAI moves to each new snapshot; name a dated snapshot such as 'openai:gpt-4o-2024-08-06', or a stable code such as 'openai:gpt-5.4-mini'

$ dossier run incident-review --plan          # model: openai:gpt-5-latest
pipeline.yaml, line 9: model 'openai:gpt-5-latest' is a name OpenAI moves to each new snapshot; name a dated snapshot such as 'openai:gpt-4o-2024-08-06', or a stable code such as 'openai:gpt-5.4-mini'
```

Both exit 2, and the call log still holds five lines.

- **The difference** is what OpenAI does with the name (R9.14). `gpt-5.4-mini`
  is a stable code: it names one model and is not re-pointed. `gpt-4o` is a
  family alias that OpenAI moves to each new snapshot, and nothing in its shape
  says so. That is why `dossier` refuses it by name, from a short list, and
  refuses `-latest`, `-preview` and `-exp` by pattern.
- **If it had been accepted**, the key would hold the string `openai:gpt-4o`
  (R5.3). A month later another model would answer under the same key. The
  cache would serve last month's answers as if they were this one's, and a
  replay would "reproduce" a run that model never made. A pin that is not one
  is worse than no cache at all (R0.6).

## Task 4 — which keys a model moves

```console
$ dossier run incident-review --plan          # summary: model: openai:gpt-4o-2024-08-06
incident-review  4 document(s) · model openai:gpt-5.4-mini
compared against 20261002T062444Z-07b1
  extract: cached
! summary: model changed
      model: openai:gpt-4o-2024-08-06
1 of 2 step(s) would run · nothing written

$ dossier run incident-review --plan          # model: openai:gpt-4o-mini-2024-07-18
incident-review  4 document(s) · model openai:gpt-4o-mini-2024-07-18
compared against 20261002T062444Z-07b1
! extract: model changed
! summary: upstream changed
      model: openai:gpt-5.4
2 of 2 step(s) would run · nothing written

$ dossier run incident-review
run 20261002T062447Z-5fea · runs/20261002T062447Z-5fea/manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · 1,573 tokens in · 644 out
  summary: 1 document(s) · 1 from cache · 0 failed

$ dossier run incident-review                 # the pipeline's model put back
run 20261002T062448Z-73f9 · runs/20261002T062448Z-73f9/manifest.json
  extract: 4 document(s) · 4 from cache · 0 failed
  summary: 1 document(s) · 1 from cache · 0 failed
```

- **The plan was not wrong. It could not know.** `summary`'s key holds the hash
  of what `extract` answered (R5.2), and that is known only once `extract` has
  been asked. The plan asks nothing (R4.6), so it can only say "upstream
  changed". The other model, here the stub, answered the same bytes. So
  `summary`'s key did not move, and its answer was served. A real cheaper model
  answering differently would have moved it.
- **Putting it back** returned every key to one the cache already held
  (R5.13). Nothing was asked, so nothing was spent, and the run prints no
  tokens at all.

## Task 5 — what it cost

The first run's records:

```
extract/PLAY-1001.md.meta.json  attempts 1  tokens {'input': 404, 'output': 161}
extract/PLAY-1002.md.meta.json  attempts 1  tokens {'input': 349, 'output': 151}
extract/PLAY-1003.md.meta.json  attempts 1  tokens {'input': 388, 'output': 167}
extract/PLAY-1004.md.meta.json  attempts 1  tokens {'input': 432, 'output': 165}
summary/aggregate.meta.json     attempts 1  tokens {'input': 1285, 'output': 61}
```

The four `extract` records add up to the run's line: 1,573 in, 644 out.

Terminal 1, the retry layered in front:

```bash
E=playground/22-what-a-run-costs-and-how-fast-it-goes/resources
.venv/bin/python playground/toolkit/stub_model.py \
  --replies $E/replies-retry.json --replies $E/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl --usage
```

Terminal 2:

```console
$ printf '\nReviewed at the weekly incident review on 2026-04-10.\n' >> inbox/incidents/PLAY-1003.md
$ dossier sync incident-review
incidents  4 known · 1 changed · 0 new -> 4 fetched
      PLAY-1003.md  9c5d76c1930794d25fd2bb6356a7a4f800ae1f5f9c22ba98b81aec45b67769d4 -> 56036303a3ec4e8649a16fc73cfb32dc3cfa51d8fd87f7eac861efa5fd93f775
ledger updated · 1 new snapshots · 0 tombstoned

$ dossier run incident-review
warning: the source has moved since run 20261002T062448Z-73f9: PLAY-1003.md re-snapshotted
run 20261002T062453Z-1502 · runs/20261002T062453Z-1502/manifest.json
  extract: 4 document(s) · 3 from cache · 0 failed · 911 tokens in · 184 out
  summary: 1 document(s) · 1 from cache · 0 failed
```

PLAY-1003's record: `attempts 2`, `tokens {'input': 911, 'output': 184}`. The
log's last two calls are both PLAY-1003, at 1,606 and 2,034 characters of
prompt. The second is the first with the `<validation_error>` that asked for a
correction (R6.2): 402 tokens in, then 509.

Terminal 1, with no `--usage`:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies $E/replies.json --port 8099 --log /tmp/dossier-calls.jsonl
```

```console
$ printf 'Action items are tracked in the review notes.\n' >> inbox/incidents/PLAY-1003.md
$ dossier sync incident-review
...
$ dossier run incident-review
warning: the source has moved since run 20261002T062453Z-1502: PLAY-1003.md re-snapshotted
run 20261002T062458Z-bede · runs/20261002T062458Z-bede/manifest.json
  extract: 4 document(s) · 3 from cache · 0 failed · tokens not reported
  summary: 1 document(s) · 1 from cache · 0 failed
```

PLAY-1003's record: `attempts 1`, `tokens {'input': None, 'output': None}`.

- **The refused attempt is counted** because it was paid for (R5.11 row 2). The
  bill does not care that the answer was not kept, and a cost line that left
  out retries would hide exactly the prompts that need work (R5.12 row 4).
- **Nothing printed, and "not reported", are two different facts.** Task 4's
  last run asked nothing, so it spent nothing, and there is nothing to say.
  Here a call was made, and the endpoint did not say what it cost. `0` would
  claim a free answer. `null` says nobody counted it (R9.18 row 4), which is
  what a passthrough that strips `usage` looks like.
- **`summary` is still cached**, because PLAY-1003's extraction is the same
  bytes as before. The note grew a line that holds no field. `summary`'s key
  holds `extract`'s output, not the notes (R5.2).
- **Tokens in a key** would move the key every time a provider counted
  differently, for the same question and the same answer. Two runs of one
  pipeline would stop sharing a cache over a bookkeeping detail. A key holds
  what an answer was asked, and a record holds what it cost (R5.11 row 6).

## Task 6 — how fast

Terminal 1:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies $E/replies.json --port 8099 --log /tmp/dossier-calls.jsonl --usage --delay 1
```

```console
$ rm -rf .dossier/cache/stage && time dossier run incident-review
run 20261002T062502Z-f16f · runs/20261002T062502Z-f16f/manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · 1,598 tokens in · 644 out
  summary: 1 document(s) · 0 from cache · 0 failed · 1,285 tokens in · 61 out

real	0m5.774s

$ rm -rf .dossier/cache/stage && time dossier run incident-review --concurrency 4
run 20261002T062508Z-136e · runs/20261002T062508Z-136e/manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · 1,598 tokens in · 644 out
  summary: 1 document(s) · 0 from cache · 0 failed · 1,285 tokens in · 61 out

real	0m2.756s

$ diff -r runs/20261002T062502Z-f16f runs/20261002T062508Z-136e
diff -r .../extract/PLAY-1001.md.meta.json .../extract/PLAY-1001.md.meta.json
22c22
<   "run_id": "20261002T062502Z-f16f",
---
>   "run_id": "20261002T062508Z-136e",
  (the same for PLAY-1002, PLAY-1003, PLAY-1004 and summary/aggregate.meta.json)
diff -r .../manifest.json .../manifest.json
2,3c2,3
<   "run_id": "20261002T062502Z-f16f",
<   "started_at": "2026-10-02T06:25:02.387125Z",
---
>   "run_id": "20261002T062508Z-136e",
>   "started_at": "2026-10-02T06:25:08.212243Z",
```

The extractions and the summary are byte for byte the same. (1,598 is one more
than task 5's first count: PLAY-1003 is two lines longer now.)

```console
$ dossier run incident-review --concurrency 0
incident-review: --concurrency is '0'; it takes a whole number of at least 1.

$ echo "DOSSIER_CONCURRENCY=2.5" >> .env && dossier run incident-review
incident-review: DOSSIER_CONCURRENCY is '2.5'; it takes a whole number of at least 1.

$ # DOSSIER_CONCURRENCY=4 in .env
$ rm -rf .dossier/cache/stage && time dossier run incident-review
run 20261002T062512Z-c3b7 · runs/20261002T062512Z-c3b7/manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · 1,598 tokens in · 644 out
  summary: 1 document(s) · 0 from cache · 0 failed · 1,285 tokens in · 61 out

real	0m2.816s

$ dossier run incident-review --plan          # concurrency: 4 in pipeline.yaml
pipeline.yaml: concurrency -- Extra inputs are not permitted
```

Every refusal exits 2.

- **The other second** is `summary`. It is one call, and it waits for every
  `extract` answer, because it reads them all. Steps still run one after
  another (R9.19). `--concurrency 40` would win nothing more here, and on a
  real provider it would be the fastest way to meet a rate limit.
- **Order.** Each answer is put back in document order before anything is
  written, so what reaches `runs/` cannot tell which answer came back first
  (R9.19 row 2). If it could, a replay would stop being byte for byte.
- **Not in `pipeline.yaml`**, because how fast a pipeline runs is not part of
  what it is (R9.19 row 8). Two people with different machines and different
  rate limits run the same pipeline. If the setting were part of the pipeline,
  it would be part of the pipeline's hash, and the setting would move it.
- **A `429`** is sent again, up to twice, waiting what the server's
  `Retry-After` asks or backing off when it asks nothing (R9.17). After that
  the request fails. This retry is about transport, and is separate from R6.2's
  one retry, which is about content.

## Task 7 — what MLflow records

```bash
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/22/mlflow.db \
  --default-artifact-root file://$PWD/playground/work/22/mlartifacts \
  --host 127.0.0.1 --port 5001
```

On Windows, write the artifact root as `file:///C:/...`. Written as `C:/...`,
MLflow reads `c` as a URI scheme, and every trace is lost with a warning.

```console
$ rm -rf .dossier/cache/stage && dossier run incident-review --label nightly
run 20261002T062525Z-571f · runs/20261002T062525Z-571f/manifest.json
recorded to MLflow: dossier-audit/incident-review/run · run 20261002T062525Z-571f
  extract: 4 document(s) · 0 from cache · 0 failed · 1,598 tokens in · 644 out
  summary: 1 document(s) · 0 from cache · 0 failed · 1,285 tokens in · 61 out

$ python ../../22-what-a-run-costs-and-how-fast-it-goes/resources/read_back.py http://127.0.0.1:5001
name    20261002T062525Z-571f · nightly
label   nightly
param   concurrency = 4
param   model = openai:gpt-5.4-mini
param   model/summary = openai:gpt-5.4
metric  tokens_in = 2883
metric  tokens_out = 705
span    extract · PLAY-1001.md  openai:gpt-5.4-mini  in 404 out 161
span    extract · PLAY-1002.md  openai:gpt-5.4-mini  in 349 out 151
span    extract · PLAY-1003.md  openai:gpt-5.4-mini  in 413 out 167
span    extract · PLAY-1004.md  openai:gpt-5.4-mini  in 432 out 165
span    summary · *  openai:gpt-5.4  in 1285 out 61
```

`concurrency` is `4`, from `DOSSIER_CONCURRENCY` in `.env`. MLflow also
prints a line of its own while it flushes traces at exit.

- **`tokens_in`** is 1,598 + 1,285, the two steps' lines (R11.20). Every number
  in the record is one the command already printed.
- **`0` and absent.** A run served from cache asked nothing, so it spent `0`,
  and that is a count. A run against a stub without `--usage` asked and was
  told nothing, so the record has no `tokens_in` at all (R11.20 rows 4 and 5).
  It is the same distinction as task 5, kept all the way to the dashboard.
- **`concurrency`** is in the record because it explains the run's duration:
  two runs over the same snapshots, one taking twice as long, are compared
  knowing why. It is in no key, because nothing written depends on it
  (R11.21 row 5, R10.4).
