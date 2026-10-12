# 26 · A client, masked all the way through

**You will build:** exercise 25's four notes that name Erika Mustermann, taken
past the run. A judge is calibrated on candidate answers that name her. A gold
set written against the original notes scores a run that only ever saw
placeholders. Then MLflow, and last an index you search for her by name.

**You will learn:**
- where a masked view keeps the values it replaced, and what never holds them;
- how a value written by a person gets the same placeholder as in the note;
- why a value the note does not hold takes a new number;
- why gold is written against the original note, and how `eval` compares it;
- what MLflow records about masking, and that it records no value;
- what an index of a masked pipeline holds, and what its embedding model is asked;
- why an index's masking can never change under it;
- what a search for a client's name finds, and what it cannot find;
- why a filter that names her is refused rather than masked.

**Needs the masking extras, as exercise 25 does.** Tasks 1 to 3 run offline,
against the stub. Task 4 starts a local MLflow server with a database, as
exercise 12 does. **Tasks 5 to 7 need what exercise 20 needs: Docker, Ollama
and about 10 GB of free RAM.** Do them last, in one sitting, with little else
open.

---

## Background, in one paragraph

Exercise 25 masked what a run shows a model. A pipeline has four more roads
out. `calibrate` shows a judge candidate answers. `eval` compares a run's
answers with gold. Both were written by a person, against the original note, so
they name the client the way the note does. `dataset publish` sends that gold to
MLflow. `embed` writes the notes into an index other systems read, and `search`
sends a query to the embedding model. Spec 021's parts 3 and 4 close each road
the same way. Each masked view keeps its note's mapping, placeholder to value,
on this machine. A value a person wrote is masked with that mapping, so the
client is `[PERSON_2]` in the note, the candidate, the gold and the dataset
alike.

---

## Setup

Terminal 1, the stub. It is exercise 25's capturing launcher, with this
exercise's replies. The judge's rules come first:

```bash
mkdir -p playground/work/26
.venv/bin/python playground/25-a-client-masked-before-it-leaves/resources/stub_model_capturing.py \
  --replies playground/26-a-client-masked-all-the-way-through/resources/replies-judge.json \
  --replies playground/26-a-client-masked-all-the-way-through/resources/replies.json \
  --port 8099 --log playground/work/26/calls.jsonl
```

Terminal 2:

```bash
E25=playground/25-a-client-masked-before-it-leaves
E=playground/26-a-client-masked-all-the-way-through
mkdir -p playground/work/26/inbox/tickets
cp -r $E25/solution/workspace/. playground/work/26/
cp -r $E/solution/workspace/. playground/work/26/
cp $E25/resources/tickets/*.md playground/work/26/inbox/tickets/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/26/.env
cd playground/work/26
D=../../../.venv/bin/dossier
P=../../../.venv/bin/python
R=../../26-a-client-masked-all-the-way-through/resources
```

The workspace is exercise 25's prepared one: the same four notes and the same
`masking/cid.yaml`. This exercise's files go on top of it:

- a prompt that asks for two things;
- `schemas/incident.yaml`, with `affected_client`, a `reference`, and
  `root_cause`, a `free_text` field with a judge;
- the judge's rubric;
- `acl:` on the source, and `indexes/masked-tickets.yaml`, for task 5.

Start from 25's prepared files rather than your own 25 workspace. Yours holds
task 5's `PLAY-6005` and the runs of a one-field pipeline.

`resources/` holds four small readers. Each prints what it read, and how many
of the seven canaries of `specs/_fixtures.md` it found:

| Script | Reads |
|---|---|
| `calls.py` | the stub's call log: one line per call, a judge's call by its claim |
| `views.py` | every masked view under `.dossier/cache/mask/`, and its mapping |
| `mlflow_canaries.py` | every run, trace and dataset record an MLflow server holds |
| `asked.py` | what the embedding model was asked, from task 5's recorder |

---

## Task 1 — where the mapping is kept (R21.21)

```bash
$D sync incident-audit && $D run incident-audit
$P $R/calls.py calls.jsonl
$P $R/views.py
```

1. How many of the seven values did each call carry?
2. `views.py` finds eight views for four notes. What are the other four?
3. Each view's mapping sits under `.dossier/cache/mask-values/`, at the path
   its view has under `mask/`. Open PLAY-6001's. What is `[PERSON_2]`, and
   what does the mapping's `.meta.json` say?
4. Search the workspace for the seven values:

   ```bash
   grep -rlF -e "Erika Mustermann" -e "Hans Muster" -e "erika.mustermann@example.ch" \
     -e "+41 44 555 01 23" -e "CH93 0076 2011 6238 5295 7" -e "756.1234.5678.97" \
     -e "CIF 0042-118733" .dossier runs | sed -E 's#/[0-9a-f]{2}/.*##' | sort | uniq -c
   ```

   Which three places hold them? Which places never do?

**Checkpoint.** Four calls, `0 of 7` each. Three places, four files each. Not
one under `runs/`.

## Task 2 — a judge shown masked candidates (R21.20, R21.22)

Read `resources/calibration-sample/root_cause.jsonl`. It holds twenty candidate
root causes, written against the original notes, with a person's verdict on
each. Most of them name the client in some way. Copy it in, with the proposed
bar beside it. As in exercise 07, the sample and the bar are yours to agree
to, not the assistant's:

```bash
mkdir -p gold/incidents/samples
cp $R/calibration-sample/root_cause.jsonl gold/incidents/samples/
cp $R/judge-threshold/judge.yaml gold/incidents/
: > calls.jsonl
$D calibrate incident-audit --gold gold/incidents
$P $R/calls.py calls.jsonl
```

1. `rc-02` and `rc-07` both write `Erika Mustermann's`. What is each judge
   shown in its place, and why are the two numbers different?
2. `rc-03` writes her name in capitals. `rc-04` writes `Ms Mustermann`. Which
   takes the note's number, and which takes a new one? The rule did what it
   says. What has the judge lost?
3. `rc-17`'s phone number scores 0.4 on its own, below the threshold (25,
   task 5). It is masked anyway. Why?
4. Presidio's span on `Erika Mustermann's` takes in the `'s`. What does the
   judge see where the `'s` was?
5. `rc-01` holds no value. How is it shown?

Now comment out `masking:` in `pipeline.yaml`, empty the log, and calibrate
once more. Read the log, and the exit code. Put the line back.

**Checkpoint.** `100.0% agreement over 20 cases`, and twenty calls at
`0 of 7`. Unmasked, the first call carries `7 of 7` and the second is refused
by the stub.

## Task 3 — gold written against the original note (R21.23)

`resources/verified-answers/` proposes four gold files. Each says
`affected_client` is `Erika Mustermann`, as the note does. Read them, then
copy them in:

```bash
cp $R/verified-answers/*.json gold/incidents/
: > calls.jsonl
$D eval incident-audit --gold gold/incidents
$P $R/calls.py calls.jsonl
```

Then change `PLAY-6001.json`'s `affected_client` to `Hans Muster`, the other
person in that note, and run `eval` again. Put it back.

1. The run answered `[PERSON_2]` for PLAY-6001, and `[PERSON_1]` for the
   others. Gold says `Erika Mustermann` for all four. Why is that 100%?
2. What does `eval` print for the wrong gold value? Which name is in it?
3. Why is gold not written in placeholders, when that is what the run sees?

**Checkpoint.** `affected_client 100.0%`, then `75.0%` with one line naming
PLAY-6001.

## Task 4 — what MLflow holds (R21.25, R21.24)

Terminal 3, MLflow with a database, as in exercise 12:

```bash
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/26/mlflow.db \
  --artifacts-destination file://$PWD/playground/work/26/mlartifacts \
  --host 127.0.0.1 --port 5000
```

**On Windows**, write `--artifacts-destination` as `file:///C:/...`. A bare
`C:/...` is read as a URI whose scheme is `c`, and every trace is lost.

Back in terminal 2:

```bash
printf 'DOSSIER_MLFLOW_ENABLED=true\nDOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5000\n' >> .env
: > calls.jsonl
$D run incident-audit
wc -l < calls.jsonl
$D calibrate incident-audit --gold gold/incidents
$D eval incident-audit --gold gold/incidents
$D dataset publish incident-audit --gold gold/incidents
$P $R/mlflow_canaries.py http://127.0.0.1:5000
```

Then search the store's own files, the database and the artifacts:

```bash
grep -rlaF -e "Erika Mustermann" -e "Hans Muster" -e "erika.mustermann@example.ch" \
  -e "+41 44 555 01 23" -e "CH93 0076 2011 6238 5295 7" -e "756.1234.5678.97" \
  -e "CIF 0042-118733" mlflow.db mlartifacts; echo "grep exit $?"
grep -rlaF "[PERSON_2]" mlflow.db mlartifacts
```

1. The run asked the stub nothing. Where do its `masked/` metrics come from?
2. Why `masked/PERSON=8`, and 4 of every other type?
3. Read PLAY-6001's record in the dataset. Gold wrote `Erika Mustermann's
   settlement`. What was published?
4. Only some traces hold a placeholder. What do the calibration's traces
   hold? Why does `0 canaries` mean more for the run's traces than for those?

**Checkpoint.** The run's metrics, four `[PERSON_n]` expectations, and
`canaries params 0 · metrics 0 · tags 0 · traces 0 · dataset records 0`. The
first `grep` finds nothing.

---

Tasks 5 to 7 write an index and ask a real embedding model. Read exercise 20's
"Read this before you start" first. From the repository root:

```bash
docker compose -f dev/index/docker-compose.yml up -d     # Postgres 17 + pgvector, 127.0.0.1:5435
ollama pull qwen3-embedding:4b-fp16                      # 8 GB, once
```

## Task 5 — a masked index (R21.15, R21.16)

There is no stub for an embedding model. Terminal 4 starts a recorder in front
of the real Ollama instead. It passes every request through, and logs every
text it was asked to embed:

```bash
.venv/bin/python playground/26-a-client-masked-all-the-way-through/resources/ollama_recorder.py \
  --port 11435 --log playground/work/26/embed-calls.jsonl
```

Read `indexes/masked-tickets.yaml`. It names its pipeline, and has no switch
for masking. In terminal 2:

```bash
printf 'DOSSIER_INDEX_DSN=postgresql://dossier:dossier@127.0.0.1:5435/dossier\nDOSSIER_OLLAMA_URL=http://127.0.0.1:11435\n' >> .env
Q() { docker exec dossier-index psql -U dossier -d dossier -c "$1"; }
find .dossier/cache/mask -type f | wc -l
$D embed masked-tickets
find .dossier/cache/mask -type f | wc -l
$P $R/asked.py embed-calls.jsonl
Q "select text from dossier_index.chunks where index = 'masked-tickets'
   and document_id = 'incidents:PLAY-6001.md' and kind = 'record'"
Q "select count(*) as chunks,
     count(*) filter (where concat_ws(' ', d.key, d.title, d.filter_values, c.heading_path,
       c.text, c.text_search) ~* '(muster|555|ch93|1234|0042)') as with_a_canary,
     count(*) filter (where c.text ~ '\[[A-Z_]+_[0-9]+\]') as with_a_placeholder
   from dossier_index.chunks c join dossier_index.documents d using (index, document_id)
   where c.index = 'masked-tickets'"
```

1. The run masked every note in task 1. Did `embed` mask any of them again?
2. What was the embedding model asked about, and with which placeholders?
3. The record chunk carries the run's `root_cause`. What does it say about the
   client?
4. The query on Postgres looks for parts of each value, not the whole value.
   Why is that the stricter search, for a `tsvector`?

Now a file named after the client, as in exercise 25's task 4:

```bash
cp inbox/tickets/PLAY-6001.md inbox/tickets/Erika-Mustermann-complaint.md
$D sync incident-audit
$D embed masked-tickets
find .dossier/cache/mask -type f | wc -l
rm inbox/tickets/Erika-Mustermann-complaint.md
$D sync incident-audit
$P $R/views.py | tail -4
```

5. Was it written? What did `embed` mask, that no run had?

**Checkpoint.** `12 chunks · 12 embedded · 4 written`, sixteen view files
before and after, `0 of 7` on every text, and `with_a_canary 0`. The file
named after her is not written.

## Task 6 — an index's masking never changes under it (R21.18, R21.17)

```bash
sed -i 's/^masking:/# masking:/' pipelines/incident-audit/pipeline.yaml
$D embed masked-tickets; echo "exit $?"
sed -i 's/^# masking:/masking:/' pipelines/incident-audit/pipeline.yaml
```

1. What is refused, and before what? What does Postgres keep that makes
   rewriting the rows no remedy?
2. `.dossier/index/masked-tickets.json` says how the index was written. Why is
   that on this machine and not in Postgres? What happens if you delete this
   workspace and embed the same index from a new one?

Now change the masking, but not whether it masks. Add the vendor the spec's
own allow-list names, then embed, run, and embed:

```bash
echo Oracle >> pipelines/incident-audit/masking/allow.txt
RUNS="select key, run_id from dossier_index.documents where index = 'masked-tickets' order by key"
$D embed masked-tickets
docker exec dossier-index psql -U dossier -d dossier -tA -c "$RUNS"
$D run incident-audit
$D embed masked-tickets
docker exec dossier-index psql -U dossier -d dossier -tA -c "$RUNS"
```

3. Why did the first `embed` carry no record? `Oracle` is in no note. What
   could a record from a run under another declaration hold?
4. Why does the second `embed` carry it again, with nothing embedded?

**Checkpoint.** Exit 2 and nothing written. Then `no record: … did not mask as
this index does`, then the record back under the new run's id.

## Task 7 — search for the client (R21.19, R21.26)

```bash
: > embed-calls.jsonl
$D search masked-tickets "Erika Mustermann complained about CIF 0042-118733" --as incident-response
$P $R/asked.py embed-calls.jsonl
$D search masked-tickets "Erika Mustermann complained about CIF 0042-118733" --as incident-response --json 2>/dev/null \
  | $P -c "import json,sys; r=json.load(sys.stdin); print(r['query']); print([x['document_id'] for x in r['results']])"
```

1. What did the embedding model see of her name?
2. Every note is found. In which of them is `[PERSON_1]` Erika Mustermann?
   What can a search over a masked index never do with a client's name?

Then her surname alone:

```bash
: > embed-calls.jsonl
$D search masked-tickets "Mustermann settlement held" --as incident-response --limit 2
$P $R/asked.py embed-calls.jsonl
```

3. What reached the model this time? Why does `asked.py` still say `0 of 7`?

Then a filter that names her:

```bash
$D search masked-tickets "settlement held" --as incident-response --where "affected_client=Erika Mustermann"; echo "exit $?"
```

4. The query was masked, and the filter is refused. Why not mask the filter
   too? `masked-tickets` declares no filters at all, so why is the refusal
   about what the value holds rather than `not a filter`?

Last, read MLflow back once more:

```bash
$P $R/mlflow_canaries.py http://127.0.0.1:5000
grep -rlaF Mustermann mlflow.db mlartifacts
```

5. No canary is in any record. Which two things in the store hold part of her
   name, and which part of spec 021 says each is not covered?

**Checkpoint.** The query reached Ollama as `[PERSON_1] complained about
[CLIENT_NUMBER_1]`. The surname reached it as typed. The filter that names
her exits 2, naming the field and `PERSON`, and nothing is searched or
recorded.

---

## Done when

- you can say where a note's mapping is kept, and name the places that never
  hold a value;
- you can predict the placeholder a candidate or a gold value will get, from
  its note's mapping;
- `eval` scores gold that names the client against a run that never saw her;
- you have read every record MLflow holds and found no canary in one;
- you have read every text the embedding model was asked, and found none;
- you can say what a search for a client's name finds, and why.

## Cleaning up

Stop the four terminals. Then empty the index and remove the workspace, in
that order:

```bash
Q "delete from dossier_index.chunks where index = 'masked-tickets'"
Q "delete from dossier_index.documents where index = 'masked-tickets'"
cd ../../.. && rm -rf playground/work/26
```

The record of how `masked-tickets` was written is in the workspace. Remove the
workspace first, and the rows it leaves behind are rows no record describes.
The next masked `embed` of that index refuses them (R21.18 row 2).

The solution, with the output each task produced, is in `SOLUTION.md`.
