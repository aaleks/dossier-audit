# 26 · Solution

Every command below was run against this repository, on 2026-10-11, at the
commit of `main` that made a document's value win over a masker span that
overlaps it (R21.22, #749). The masker was `presidio-analyzer` 2.2.364 with
spaCy 3.8.16 and the four `lg` models at 3.8.0. MLflow was 3.15.1 with a
SQLite backend. The output shown is the output it produced, trimmed to what
each task asks about. MLflow's line `Flushing the async trace logging queue`
is left out wherever it was printed.

The pass was on Windows, so `$D` was the worktree's `.venv/Scripts/dossier.exe`
and `$P` its `.venv/Scripts/python.exe`. The stub ran on port 8126 and MLflow
on 5026, because other exercises held the defaults. Commands and output below
say 8099 and 5000, as yours will. Absolute paths are shown as
`/…/playground/work/26/...`.

Tasks 1 to 7 were run in order, in one pass, from an empty workspace, an empty
MLflow store and an empty `masked-tickets` index. Tasks 5 to 7 are marked
**[run · Postgres + Ollama]**: they ran against the Postgres of `dev/index`
and a local Ollama serving `qwen3-embedding:4b-fp16`. The prepared answer
below was run last, from scratch, as a second pass.

What will differ in yours: run ids, cache keys, MLflow's ids and digests, and
the search's order among notes that are nearly as near.

---

## Run the prepared answer

Terminal 1, the stub:

```bash
mkdir -p playground/work/26
.venv/bin/python playground/25-a-client-masked-before-it-leaves/resources/stub_model_capturing.py \
  --replies playground/26-a-client-masked-all-the-way-through/resources/replies-judge.json \
  --replies playground/26-a-client-masked-all-the-way-through/resources/replies.json \
  --port 8099 --log playground/work/26/calls.jsonl
```

Terminal 2, MLflow with a database. On Windows, write
`--artifacts-destination` as `file:///C:/...`:

```bash
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/26/mlflow.db \
  --artifacts-destination file://$PWD/playground/work/26/mlartifacts \
  --host 127.0.0.1 --port 5000
```

Terminal 3, the recorder in front of Ollama, for the index block only:

```bash
.venv/bin/python playground/26-a-client-masked-all-the-way-through/resources/ollama_recorder.py \
  --port 11435 --log playground/work/26/embed-calls.jsonl
```

Terminal 4, once MLflow says `Application startup complete`:

```bash
E25=playground/25-a-client-masked-before-it-leaves
E=playground/26-a-client-masked-all-the-way-through
W=playground/work/26
mkdir -p $W/inbox/tickets $W/gold/incidents/samples
cp -r $E25/solution/workspace/. $W/
cp -r $E/solution/workspace/. $W/
cp $E25/resources/tickets/*.md $W/inbox/tickets/
cp $E/resources/verified-answers/*.json $W/gold/incidents/
cp $E/resources/calibration-sample/root_cause.jsonl $W/gold/incidents/samples/
cp $E/resources/judge-threshold/judge.yaml $W/gold/incidents/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample $W/.env
printf 'DOSSIER_MLFLOW_ENABLED=true\nDOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5000\n' >> $W/.env
cd $W
D=../../../.venv/bin/dossier
P=../../../.venv/bin/python
R=../../26-a-client-masked-all-the-way-through/resources
$D sync incident-audit && $D run incident-audit
$D calibrate incident-audit --gold gold/incidents
$D eval incident-audit --gold gold/incidents
$D dataset publish incident-audit --gold gold/incidents
$P $R/calls.py calls.jsonl | tail -1
$P $R/mlflow_canaries.py http://127.0.0.1:5000
```

```
incidents  0 known · 0 changed · 4 new -> 4 fetched
ledger updated · 4 new snapshots · 0 tombstoned
recorded to MLflow: dossier-audit/incident-audit/sync
run 20261011T183154Z-82b1 · /…/playground/work/26/runs/20261011T183154Z-82b1/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20261011T183154Z-82b1
  extract: 4 document(s) · 0 from cache · 0 failed · tokens not reported
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
recorded to MLflow: dossier-audit/incident-audit/calibrate
4 documents · 2 fields · overall 100.0%
  affected_client    100.0%
  root_cause         100.0%   (4 judged)
recorded to MLflow: dossier-audit/incident-audit/eval
incidents · 4 records · digest bc9d1c07
published to MLflow: dossier-audit/incident-audit/eval (d-c94c55e4cddd4744a55a8c96adac69ca)
28 calls
run      dossier-audit/incident-audit/calibrate   calibrate incidents · openai:gpt-5.4-mini
run      dossier-audit/incident-audit/eval        eval 20261011T183154Z-82b1 · openai:gpt-5.4-mini
run      dossier-audit/incident-audit/run         20261011T183154Z-82b1                        masked/CH_AHV=4 masked/CLIENT_NUMBER=4 masked/EMAIL_ADDRESS=4 masked/IBAN_CODE=4 masked/PERSON=8 masked/PHONE_NUMBER=4
run      dossier-audit/incident-audit/sync        sync 20261011T183150Z
dataset  incidents
         PLAY-6001.md  {"affected_client": "[PERSON_2]", "root_cause": "The nightly settlement export was scheduled at a local time that did not exist on the night the clocks changed, so it never ran, and [PERSON_2]'s settlement was held for two days."}
         PLAY-6002.md  {"affected_client": "[PERSON_1]", "root_cause": "Eine Firewall-Regel wurde bei der nächtlichen Änderung entfernt, und die Kassenterminals konnten den Zahlungsdienst nicht mehr erreichen."}
         PLAY-6003.md  {"affected_client": "[PERSON_1]", "root_cause": "La mise à jour du service de paiement a remplacé le certificat sans redémarrer les passerelles, qui ont refusé toutes les connexions."}
         PLAY-6004.md  {"affected_client": "[PERSON_1]", "root_cause": "L'esportazione notturna era programmata a un orario che non esisteva nella notte del cambio dell'ora, e non è stata eseguita."}
traces   dossier-audit/incident-audit/calibrate   20
traces   dossier-audit/incident-audit/eval        4
traces   dossier-audit/incident-audit/run         4
         8 of 28 traces hold a placeholder
canaries params 0 of 27 · metrics 0 of 25 · tags 0 of 31 · traces 0 of 28 · dataset records 0 of 4
```

Then the index, with Postgres and Ollama up (exercise 20's setup) and an empty
`masked-tickets`. **[run · Postgres + Ollama]**

```bash
printf 'DOSSIER_INDEX_DSN=postgresql://dossier:dossier@127.0.0.1:5435/dossier\nDOSSIER_OLLAMA_URL=http://127.0.0.1:11435\n' >> .env
$D embed masked-tickets
$D search masked-tickets "Erika Mustermann complained about CIF 0042-118733" --as incident-response --limit 1
$P $R/asked.py embed-calls.jsonl
```

```
masked-tickets · 12 chunks · 12 embedded · 0 cached · 4 written · 0 removed
recorded to MLflow: dossier-audit/incident-audit/embed
masked-tickets · 1 document · as incident-response
1. PLAY-6001.md · PLAY-6001 Settlement export did not run
   PLAY-6001 Settlement export did not run
   Reported by [PERSON_1] on 2026-09-14. Assigned to k.oyelaran. The affected client is [PERSON_2], AHV number [CH_AHV_1], client reference [CLIENT_NUMBER_1]. She called from her phone,…
recorded to MLflow: dossier-audit/incident-audit/search
qwen3-embedding:4b-fp16 · 12 texts
[…the twelve texts of task 5, each 0 of 7]
qwen3-embedding:4b-fp16 · 1 texts
  0 of 7  Instruct: Given a question about incidents, retrieve the passages of incident records and documents that answer it Query:[PERSON_1] complained about [CLIENT_NUMBER_1]
2 requests · 13 texts
```

If `masked-tickets` already holds rows from an earlier workspace, `embed`
refuses them, because no record on this machine says how they were written
(R21.18 row 2). Empty it first, as "Cleaning up" in the README says.

---

## Task 1 — where the mapping is kept (R21.21)

```console
$ $D sync incident-audit && $D run incident-audit
incidents  0 known · 0 changed · 4 new -> 4 fetched
ledger updated · 4 new snapshots · 0 tombstoned
run 20261011T182331Z-e31e · /…/playground/work/26/runs/20261011T182331Z-e31e/manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · tokens not reported
$ $P $R/calls.py calls.jsonl
step   PLAY-6001.md  ·  0 of 7
step   PLAY-6002.md  ·  0 of 7
step   PLAY-6003.md  ·  0 of 7
step   PLAY-6004.md  ·  0 of 7
4 calls
$ $P $R/views.py
# PLAY-6001 Settlement export did not run
  eb64a330eabe…  en  masked: CH_AHV 1, CLIENT_NUMBER 1, EMAIL_ADDRESS 1, IBAN_CODE 1, PERSON 2, PHONE_NUMBER 1
  [CH_AHV_1]         756.1234.5678.97
  [CLIENT_NUMBER_1]  CIF 0042-118733
  [EMAIL_ADDRESS_1]  erika.mustermann@example.ch
  [IBAN_CODE_1]      CH93 0076 2011 6238 5295 7
  [PERSON_1]         Hans Muster
  [PERSON_2]         Erika Mustermann
  [PHONE_NUMBER_1]   +41 44 555 01 23
# PLAY-6002 Kassenterminals offline nach Firewall-Änderung
  08bea1222a5a…  de  masked: CH_AHV 1, CLIENT_NUMBER 1, EMAIL_ADDRESS 1, IBAN_CODE 1, PERSON 2, PHONE_NUMBER 1
  [CH_AHV_1]         756.1234.5678.97
  [CLIENT_NUMBER_1]  CIF 0042-118733
  [EMAIL_ADDRESS_1]  erika.mustermann@example.ch
  [IBAN_CODE_1]      CH93 0076 2011 6238 5295 7
  [PERSON_1]         Erika Mustermann
  [PERSON_2]         Hans Muster
  [PHONE_NUMBER_1]   +41 44 555 01 23
[…PLAY-6003 and PLAY-6004, numbered as PLAY-6002, read in fr and it]
PLAY 6001 md
  951860ed8ced…  en  masked: nothing
  mapping: empty
[…PLAY 6002 md to PLAY 6004 md, the same]
8 views
```

1. **None.** Each call carried `0 of 7`, as in exercise 25.
2. **The keys.** A key is shown to the model in every `<document key="...">`,
   so it is masked as well, read with its `-`, `_` and `.` as spaces (R21.8).
   Nothing was found in `PLAY 6001 md`, so its view is the key itself and its
   mapping is empty (R21.21 row 4).
3. **`[PERSON_2]` is Erika Mustermann in PLAY-6001**, because Hans Muster is
   named first. The mapping is kept in the namespace `mask-values`, under the
   view's own key, `K_mask`. Its `.meta.json` says only what it is:

   ```console
   $ cat .dossier/cache/mask-values/eb/64/*.meta.json
   {
     "cache_key": "eb64a330eabe8cd120e30d869d84352ea3378574a9e31abb71162a8c8d3cc6a1",
     "kind": "mask-values"
   }
   ```

   The view's record, beside it under `mask/`, counts the values by type and
   names none (exercise 25, task 2). Anyone holding `.dossier/cache/` holds
   the values. That is the same exposure as the snapshots, and was decided so
   on 2026-10-03.
4. **The snapshots, the conversions and the mappings.**

   ```console
   $ grep -rlF -e "Erika Mustermann" -e "Hans Muster" -e "erika.mustermann@example.ch" \
       -e "+41 44 555 01 23" -e "CH93 0076 2011 6238 5295 7" -e "756.1234.5678.97" \
       -e "CIF 0042-118733" .dossier runs | sed -E 's#/[0-9a-f]{2}/.*##' | sort | uniq -c
         4 .dossier/cache/convert
         4 .dossier/cache/mask-values
         4 .dossier/snapshots
   $ grep -o '"value": "[^"]*"' runs/*/extract/PLAY-6001.md.json
   "value": "[PERSON_2]"
   "value": "The nightly settlement export was scheduled at a local time that did not exist on the night the clocks changed, so it never ran, and [PERSON_2]'s settlement was held for two days."
   ```

   Never `runs/`: its answers, its manifest and its provenance records. Never
   `mask/`, the views and their records, and never `stage/`. The run's answers
   hold placeholders, because a model shown placeholders answers in them.

## Task 2 — a judge shown masked candidates (R21.20, R21.22)

```console
$ $D calibrate incident-audit --gold gold/incidents
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
$ $P $R/calls.py calls.jsonl
judge  PLAY-6001.md  The nightly settlement export was scheduled at a local time that did not exist on the night the clocks changed, so it never ran.  ·  0 of 7
judge  PLAY-6001.md  The export never ran on the night the clocks changed, so [PERSON_2]'s settlement was held for two days.  ·  0 of 7
judge  PLAY-6001.md  [PERSON_2]'s settlement was held because the export was scheduled at a time that did not exist.  ·  0 of 7
judge  PLAY-6001.md  [PERSON_3] gave the bank a wrong account number, so her settlement was held.  ·  0 of 7
judge  PLAY-6001.md  [PERSON_1] cancelled the nightly export by mistake.  ·  0 of 7
judge  PLAY-6002.md  Eine Firewall-Regel wurde bei der nächtlichen Änderung entfernt, und die Kassenterminals konnten den Zahlungsdienst nicht mehr erreichen.  ·  0 of 7
judge  PLAY-6002.md  A firewall rule removed in the nightly change cut the cash terminals off from the payment service, and [PERSON_1]'s account was blocked while it lasted.  ·  0 of 7
judge  PLAY-6002.md  Die Kassenterminals erreichten den Zahlungsdienst nicht mehr, weil eine Firewall-Regel entfernt wurde.  ·  0 of 7
judge  PLAY-6002.md  The Kafka consumer lag reported by [PERSON_2] caused the outage.  ·  0 of 7
judge  PLAY-6002.md  Die AHV-Nummer [CH_AHV_1] von [PERSON_1] wurde vom Zahlungsdienst abgelehnt.  ·  0 of 7
judge  PLAY-6003.md  La mise à jour du service de paiement a remplacé le certificat sans redémarrer les passerelles, qui ont refusé toutes les connexions.  ·  0 of 7
judge  PLAY-6003.md  The payment service update replaced the certificate without restarting the gateways, which then refused every connection.  ·  0 of 7
judge  PLAY-6003.md  La cliente [PERSON_1] a été bloquée parce que les passerelles n'ont pas été redémarrées après le changement de certificat.  ·  0 of 7
judge  PLAY-6003.md  Le compte [IBAN_CODE_1] de la cliente avait été clôturé, donc le virement a été refusé.  ·  0 of 7
judge  PLAY-6003.md  [PERSON_2] restarted the gateways before the certificate was replaced.  ·  0 of 7
judge  PLAY-6004.md  L'esportazione notturna era programmata a un orario che non esisteva nella notte del cambio dell'ora, e non è stata eseguita.  ·  0 of 7
judge  PLAY-6004.md  She called from [PHONE_NUMBER_1] because her transfer was held after the nightly export never ran.  ·  0 of 7
judge  PLAY-6004.md  [PERSON_1]'s transfer was held because the nightly export never ran.  ·  0 of 7
judge  PLAY-6004.md  The client wrote from [EMAIL_ADDRESS_1] to cancel the transfer.  ·  0 of 7
judge  PLAY-6004.md  Il bonifico è stato sospeso perché il cliente [CLIENT_NUMBER_1] era bloccato.  ·  0 of 7
20 calls
```

Each judge is shown the note's masked view, and the candidate masked with that
note's numbering. `rc-02`'s whole prompt:

```
Is the stated root cause supported by the named document?

Document PLAY-6001.md, in full:
<document>
# PLAY-6001 Settlement export did not run

Reported by [PERSON_1] on 2026-09-14. Assigned to k.oyelaran.

The affected client is [PERSON_2], AHV number [CH_AHV_1], client
reference [CLIENT_NUMBER_1]. She called from her phone, [PHONE_NUMBER_1], and
wrote to the desk from [EMAIL_ADDRESS_1]. Her settlement to account
[IBAN_CODE_1] was held for two days.
[…]
</document>

Stated root cause:
<claim>The export never ran on the night the clocks changed, so [PERSON_2]'s settlement was held for two days.</claim>
```

1. **`[PERSON_2]'s` and `[PERSON_1]'s`.** Each candidate is masked with its
   own note's mapping. PLAY-6001 names Hans Muster first, and PLAY-6002 names
   Erika Mustermann first. So the judge sees the client under the placeholder
   its note gives her, and can tell whether the claim is about the person the
   note says.
2. **`rc-03` takes the note's number, `rc-04` a new one.** A candidate's value
   is compared with the note's as R21.2 compares two mentions, after case
   folding, so `ERIKA MUSTERMANN` is `[PERSON_2]` (R21.22 row 2). `Ms
   Mustermann` is not a value the note holds. The masker found it, so it took
   the next number of its type, `[PERSON_3]` (R21.22 row 3). The rule did what
   it says, and the judge no longer knows that `[PERSON_3]` is the client.
   Here the verdict is "unsupported" either way. On a supported candidate,
   the judge would be asked about a stranger.
3. **Because it is the note's value.** A value the note holds is found in the
   candidate by itself, whatever the masker scores it there. In PLAY-6004
   itself the masker counted the number, so the mapping holds it as
   `[PHONE_NUMBER_1]`.
4. **The `'s` stays: `[PERSON_2]'s`.** The note's value wins over a masker
   span that overlaps it. What is left of the span is masked only if it holds
   a word, and `'s` does not (R21.22). Before that was fixed, the live check of
   2026-10-04 published `[PERSON_3] settlement was held`: a new number, and the
   `'s` swallowed (`docs/history/slices.md`).
5. **As written** (R21.22 row 4).

Unmasked, once:

```console
$ sed -i 's/^masking:/# masking:/' pipelines/incident-audit/pipeline.yaml
$ : > calls.jsonl
$ $D calibrate incident-audit --gold gold/incidents; echo "exit $?"
incident-audit: POST http://127.0.0.1:8099/api/chat/completions answered 422 Unprocessable Content: no rule matched this prompt, and the file declares no default
exit 2
$ $P $R/calls.py calls.jsonl
judge  PLAY-6001.md  The nightly settlement export was scheduled at a local time that did not exist on the night the clocks changed, so it never ran.  ·  7 of 7
judge  PLAY-6001.md  The export never ran on the night the clocks changed, so Erika Mustermann's settlement was held for two days.  ·  7 of 7
2 calls
$ sed -i 's/^# masking:/masking:/' pipelines/incident-audit/pipeline.yaml
```

The judge is shown the note as converted and the candidate as written
(R21.20 row 3). The first prompt carries all seven values from the note. The
second carries her name in the claim too. The stub's rules are written in
placeholders, so it has none for that claim, and the calibration stops.

## Task 3 — gold written against the original note (R21.23)

```console
$ cp $R/verified-answers/*.json gold/incidents/
$ : > calls.jsonl
$ $D eval incident-audit --gold gold/incidents
4 documents · 2 fields · overall 100.0%
  affected_client    100.0%
  root_cause         100.0%   (4 judged)
$ $P $R/calls.py calls.jsonl
judge  PLAY-6001.md  The nightly settlement export was scheduled at a local time that did not exist on the night the clocks changed, so it never ran, and [PERSON_2]'s settlement was held for two days.  ·  0 of 7
judge  PLAY-6002.md  eine Firewall-Regel wurde bei der nächtlichen Änderung entfernt, und die Kassenterminals konnten den Zahlungsdienst nicht mehr erreichen  ·  0 of 7
judge  PLAY-6003.md  la mise à jour du service de paiement a remplacé le certificat sans redémarrer les passerelles, qui ont refusé toutes les connexions  ·  0 of 7
judge  PLAY-6004.md  l'esportazione notturna era programmata a un orario che non esisteva nella notte del cambio dell'ora, e non è stata eseguita  ·  0 of 7
4 calls
```

The next edit changes a verified answer, and that is yours to make, by hand
(ground rule 2): set `affected_client` in `gold/incidents/PLAY-6001.json` to
`Hans Muster`. The output below was recorded when the assistant that wrote this
exercise made the same one-word change with `sed` and then copied the proposal
back. Yours should match it.

```console
$ $D eval incident-audit --gold gold/incidents     # with "Hans Muster" in PLAY-6001.json
4 documents · 2 fields · overall 87.5%
  affected_client     75.0%   <- weakest
    PLAY-6001.md   '[PERSON_2]' does not match '[PERSON_1]'
  root_cause         100.0%   (4 judged)
$ cp $R/verified-answers/PLAY-6001.json gold/incidents/
$ $D eval incident-audit --gold gold/incidents | head -1
4 documents · 2 fields · overall 100.0%
```

1. **The gold value is masked by the note's mapping before it is compared.**
   `Erika Mustermann` is `[PERSON_2]` against PLAY-6001's answer and
   `[PERSON_1]` against the others'. No masker is asked: `eval` looks for the
   values the mapping already holds (R21.23 row 1).
2. **`'[PERSON_2]' does not match '[PERSON_1]'`**: the run's answer, and the
   gold value masked. Hans Muster is `[PERSON_1]` in PLAY-6001. No name is
   printed (R21.23 row 2).
3. **Because gold is the definition of correct, written by a person against
   the evidence.** A placeholder is not a fact about the client. It is a fact
   about one note under one declaration: name a new type, or allow a word the
   masker took for a person, and a note can be numbered again. Gold written in
   names stays true, and `eval` masks it when it compares.

The eval's judge was asked about the run's answers, masked, and nothing it was
shown held a value (R21.1).

## Task 4 — what MLflow holds (R21.25, R21.24)

```console
$ printf 'DOSSIER_MLFLOW_ENABLED=true\nDOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5000\n' >> .env
$ : > calls.jsonl
$ $D run incident-audit
run 20261011T182627Z-ff8a · /…/playground/work/26/runs/20261011T182627Z-ff8a/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20261011T182627Z-ff8a
  extract: 4 document(s) · 4 from cache · 0 failed
$ wc -l < calls.jsonl
0
$ $D calibrate incident-audit --gold gold/incidents
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
recorded to MLflow: dossier-audit/incident-audit/calibrate
$ $D eval incident-audit --gold gold/incidents
4 documents · 2 fields · overall 100.0%
  affected_client    100.0%
  root_cause         100.0%   (4 judged)
recorded to MLflow: dossier-audit/incident-audit/eval
$ $D dataset publish incident-audit --gold gold/incidents
incidents · 4 records · digest bdc66883
published to MLflow: dossier-audit/incident-audit/eval (d-33e1a4b5ee3b4c12aed477af1e06166e)
$ $P $R/mlflow_canaries.py http://127.0.0.1:5000
run      dossier-audit/incident-audit/calibrate   calibrate incidents · openai:gpt-5.4-mini
run      dossier-audit/incident-audit/eval        eval 20261011T182627Z-ff8a · openai:gpt-5.4-mini
run      dossier-audit/incident-audit/run         20261011T182627Z-ff8a                        masked/CH_AHV=4 masked/CLIENT_NUMBER=4 masked/EMAIL_ADDRESS=4 masked/IBAN_CODE=4 masked/PERSON=8 masked/PHONE_NUMBER=4
dataset  incidents
         PLAY-6001.md  {"affected_client": "[PERSON_2]", "root_cause": "The nightly settlement export was scheduled at a local time that did not exist on the night the clocks changed, so it never ran, and [PERSON_2]'s settlement was held for two days."}
         PLAY-6002.md  {"affected_client": "[PERSON_1]", "root_cause": "Eine Firewall-Regel wurde bei der nächtlichen Änderung entfernt, und die Kassenterminals konnten den Zahlungsdienst nicht mehr erreichen."}
         PLAY-6003.md  {"affected_client": "[PERSON_1]", "root_cause": "La mise à jour du service de paiement a remplacé le certificat sans redémarrer les passerelles, qui ont refusé toutes les connexions."}
         PLAY-6004.md  {"affected_client": "[PERSON_1]", "root_cause": "L'esportazione notturna era programmata a un orario che non esisteva nella notte del cambio dell'ora, e non è stata eseguita."}
traces   dossier-audit/incident-audit/calibrate   20
traces   dossier-audit/incident-audit/eval        4
traces   dossier-audit/incident-audit/run         4
         4 of 28 traces hold a placeholder
canaries params 0 of 26 · metrics 0 of 21 · tags 0 of 24 · traces 0 of 28 · dataset records 0 of 4
$ grep -rlaF -e "Erika Mustermann" -e "Hans Muster" -e "erika.mustermann@example.ch" \
    -e "+41 44 555 01 23" -e "CH93 0076 2011 6238 5295 7" -e "756.1234.5678.97" \
    -e "CIF 0042-118733" mlflow.db mlartifacts; echo "grep exit $?"
grep exit 1
$ grep -rlaF "[PERSON_2]" mlflow.db mlartifacts
mlflow.db
mlartifacts/1/traces/tr-1f8fa9d4e246e8a847b87a433e0cdd8a/artifacts/traces.json
mlartifacts/1/traces/tr-724f004efb1a329d1c09e2dcf624dd0e/artifacts/traces.json
```

The first time, `run` was refused with `tracking is enabled and no MLflow
server answers at http://127.0.0.1:5000`: the server was still creating its
tables. Wait for `Application startup complete`. A fresh store was started
for the output above.

1. **From the views' records.** The run asked the stub nothing: every answer
   came from the cache, and so did every view. A masked run counts what its
   views hold, from each view's record, not what it masked this time (R21.25
   row 2).
2. **Each note holds two people and one value of every other type.** Four
   notes, so 8 and 4. The keys' views hold nothing, and are not counted.
3. **`[PERSON_2]'s settlement was held for two days`.** Gold wrote
   `Erika Mustermann's`. The expectation is masked with the note's numbering,
   so it is the placeholder the run's answer uses, and the `'s` stays (task 2,
   question 4). `affected_client` is `[PERSON_2]` for PLAY-6001 and
   `[PERSON_1]` for the rest, as `eval` compared them (R21.24 row 1).
4. **The calibration's twenty traces hold no text at all**: the case's
   document, both verdicts, and the judge's name. The eval's four hold its
   verdicts, because every verdict came from the judge cache that task 3
   filled. Only the run's four hold what was sent, and those hold
   placeholders. A search that finds no canary in a trace that recorded no
   text proves nothing. In the prepared answer, `eval` asks the judge on a
   miss, its traces hold the masked judge prompt, and 8 of 28 hold a
   placeholder.

The store's own files agree: no value in the database or the artifacts, and
placeholders in both.

---

## Task 5 — a masked index (R21.15, R21.16) **[run · Postgres + Ollama]**

```console
$ printf 'DOSSIER_INDEX_DSN=postgresql://dossier:dossier@127.0.0.1:5435/dossier\nDOSSIER_OLLAMA_URL=http://127.0.0.1:11435\n' >> .env
$ find .dossier/cache/mask -type f | wc -l
16
$ time $D embed masked-tickets
masked-tickets · 12 chunks · 12 embedded · 0 cached · 4 written · 0 removed
recorded to MLflow: dossier-audit/incident-audit/embed

real	0m56.873s
$ find .dossier/cache/mask -type f | wc -l
16
$ cat .dossier/index/masked-tickets.json
{
  "masker": {
    "declaration": "88b1a87d4f8493c44110a0382ce3fa3c1e94bef7b6a7ea3a3bcc192ae143b889",
    "id": "presidio",
    "masking_version": "2",
    "version": "1.0.0"
  }
}
$ $P $R/asked.py embed-calls.jsonl
qwen3-embedding:4b-fp16 · 12 texts
  0 of 7  PLAY-6001 Settlement export did not run Reported by [PERSON_1] on 2026-09-14. Assigned to k.oyelaran. The affected client is [PERSON_2], AHV number [CH_AHV_1], client reference [CLIENT_NUMBER_1]. She…
  0 of 7  PLAY-6001 Settlement export did not run > Root cause The nightly settlement export was scheduled at a local time that did not exist on the night the clocks changed, so it never ran.
  0 of 7  PLAY-6002 Kassenterminals offline nach Firewall-Änderung [PERSON_1] meldete am Montag, dass die orders-api nicht antwortete. Sie ist Kundin mit der Kundennummer [CLIENT_NUMBER_1] und der AHV-Nummer […
  0 of 7  PLAY-6002 Kassenterminals offline nach Firewall-Änderung > Ursache Eine Firewall-Regel wurde bei der nächtlichen Änderung entfernt, und die Kassenterminals konnten den Zahlungsdienst nicht mehr errei…
  0 of 7  PLAY-6003 Virement bloqué après la mise à jour du service de paiement La cliente [PERSON_1] a signalé que son virement depuis le compte [IBAN_CODE_1] était bloqué. Son numéro AVS est le [CH_AHV_1] et…
  0 of 7  PLAY-6003 Virement bloqué après la mise à jour du service de paiement > Cause La mise à jour du service de paiement a remplacé le certificat sans redémarrer les passerelles, qui ont refusé toutes les…
  0 of 7  PLAY-6004 Bonifico sospeso dopo il cambio dell'ora legale La cliente [PERSON_1] ha segnalato che il bonifico dal conto [IBAN_CODE_1] era sospeso. Il suo numero AVS è [CH_AHV_1] e il riferimento clien…
  0 of 7  PLAY-6004 Bonifico sospeso dopo il cambio dell'ora legale > Causa L'esportazione notturna era programmata a un orario che non esisteva nella notte del cambio dell'ora, e non è stata eseguita.
  0 of 7  root_cause: The nightly settlement export was scheduled at a local time that did not exist on the night the clocks changed, so it never ran, and [PERSON_2]'s settlement was held for two days.
  0 of 7  root_cause: eine Firewall-Regel wurde bei der nächtlichen Änderung entfernt, und die Kassenterminals konnten den Zahlungsdienst nicht mehr erreichen
  0 of 7  root_cause: l'esportazione notturna era programmata a un orario che non esisteva nella notte del cambio dell'ora, e non è stata eseguita
  0 of 7  root_cause: la mise à jour du service de paiement a remplacé le certificat sans redémarrer les passerelles, qui ont refusé toutes les connexions
1 requests · 12 texts
$ Q "select text from dossier_index.chunks where index = 'masked-tickets'
     and document_id = 'incidents:PLAY-6001.md' and kind = 'record'"
                                                                                              text
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 root_cause: The nightly settlement export was scheduled at a local time that did not exist on the night the clocks changed, so it never ran, and [PERSON_2]'s settlement was held for two days.
(1 row)

$ Q "select count(*) as chunks,
       count(*) filter (where concat_ws(' ', d.key, d.title, d.filter_values, c.heading_path,
         c.text, c.text_search) ~* '(muster|555|ch93|1234|0042)') as with_a_canary,
       count(*) filter (where c.text ~ '\[[A-Z_]+_[0-9]+\]') as with_a_placeholder
     from dossier_index.chunks c join dossier_index.documents d using (index, document_id)
     where c.index = 'masked-tickets'"
 chunks | with_a_canary | with_a_placeholder
--------+---------------+--------------------
     12 |             0 |                  5
(1 row)
```

The `asked.py` listing above was printed from the prepared answer's log, by
the same command, from its first request alone. In the tasks' pass, an earlier
`asked.py` cut each line at 110 characters, and its texts and counts were the
same. In task 7 it was run again after the change, on the same log, and that
is the output shown there.

1. **No.** Sixteen files under `mask/` before and after: the run's eight views
   and their records. `embed` took each note's view from the cache under
   `K_mask`, and asked the masker nothing about it (R21.16 row 1).
2. **Twelve texts, each with placeholders and no value.** Eight body chunks,
   each its heading path and its text, and four record chunks. The embedding
   model was asked about no value the masker detects (R21.15 row 1).
3. **`[PERSON_2]'s settlement was held for two days`**: the run's answer, as
   the run gave it, which was masked (R21.15 row 2).
4. **Because a `tsvector` holds words.** `text_search` would hold a name as
   `'erika'` and `'mustermann'`, never as `Erika Mustermann`. A search for
   whole values would miss it. `with_a_placeholder 5` says the search looked
   at masked text: four first chunks and PLAY-6001's record.

```console
$ cp inbox/tickets/PLAY-6001.md inbox/tickets/Erika-Mustermann-complaint.md
$ : > embed-calls.jsonl
$ $D sync incident-audit
incidents  4 known · 0 changed · 1 new -> 5 fetched
ledger updated · 0 new snapshots · 0 tombstoned
recorded to MLflow: dossier-audit/incident-audit/sync
$ find .dossier/cache/mask -type f | wc -l
16
$ $D embed masked-tickets
Erika-Mustermann-complaint.md: not masked, its rows are kept: its key names client data, and a key is shown to the model; rename it at the source
masked-tickets · 12 chunks · 0 embedded · 12 cached · 0 written · 0 removed
$ find .dossier/cache/mask -type f | wc -l
18
$ wc -l < embed-calls.jsonl
0
$ Q "select count(*) from dossier_index.documents where index = 'masked-tickets'"
 count
-------
     4
(1 row)

$ rm inbox/tickets/Erika-Mustermann-complaint.md
$ $D sync incident-audit
incidents  5 known · 0 changed · 0 new -> 4 fetched
      Erika-Mustermann-complaint.md  tombstoned
ledger updated · 0 new snapshots · 1 tombstoned
recorded to MLflow: dossier-audit/incident-audit/sync
$ $P $R/views.py | tail -4
[PERSON_1] complaint md
  b5eeb7e5400f…  en  masked: PERSON 1
  [PERSON_1]         Erika Mustermann
9 views
```

5. **Not written, and named** (R21.16 row 4). `embed` masked what no run had:
   the new key, read as words. That is one more view, two more files. Its
   text was never masked, and never sent: the recorder logged no request. The
   key reached neither the index nor the model. It did reach MLflow, in the
   sync's record. Task 7 finds it there.

## Task 6 — an index's masking never changes under it (R21.18, R21.17) **[run · Postgres + Ollama]**

```console
$ sed -i 's/^masking:/# masking:/' pipelines/incident-audit/pipeline.yaml
$ : > embed-calls.jsonl
$ $D embed masked-tickets; echo "exit $?"
masked-tickets: it was written masked, and its pipeline no longer masks. Its readers rely on a masked index staying masked, and Postgres keeps what is rewritten in its write-ahead log and its backups. Write a new index, or empty this one first.
exit 2
$ wc -l < embed-calls.jsonl
0
$ docker exec dossier-index psql -U dossier -d dossier -tA -c "select count(*) from dossier_index.chunks where index = 'masked-tickets'"
12
$ sed -i 's/^# masking:/masking:/' pipelines/incident-audit/pipeline.yaml
```

1. **Writing it unmasked, before anything is embedded or written.** No
   request reached the model and the twelve chunks are as they were (R21.18
   row 3). Postgres keeps a rewritten row in its write-ahead log, in its dead
   tuples until a vacuum, and in every backup. Rewriting rows does not take a
   value out of them, so the masking an index was written with is the masking
   it keeps. The other way round, masked over unmasked rows, is refused the
   same way (row 1).
2. **Because the index port reads back nothing but ids and content hashes**
   (R0.19), so Postgres cannot be asked how its rows were written. Each
   `embed` records it here instead (decided 2026-10-03). A new workspace has no
   record, and rows no record describes count as written unmasked: its first
   masked `embed` of `masked-tickets` is refused, until the index is emptied
   (R21.18 row 2).

```console
$ echo Oracle >> pipelines/incident-audit/masking/allow.txt
$ cat pipelines/incident-audit/masking/allow.txt
Kafka
Oracle
$ $D embed masked-tickets
no record: 20261011T182627Z-ff8a did not mask as this index does: it masked by another masker or declaration
masked-tickets · 8 chunks · 0 embedded · 8 cached · 4 written · 0 removed
recorded to MLflow: dossier-audit/incident-audit/embed
$ docker exec dossier-index psql -U dossier -d dossier -tA -c "select key, run_id from dossier_index.documents where index = 'masked-tickets' order by key"
PLAY-6001.md|
PLAY-6002.md|
PLAY-6003.md|
PLAY-6004.md|
$ $D run incident-audit
run 20261011T182937Z-25c2 · /…/playground/work/26/runs/20261011T182937Z-25c2/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20261011T182937Z-25c2
  extract: 4 document(s) · 4 from cache · 0 failed
$ $D embed masked-tickets
masked-tickets · 12 chunks · 0 embedded · 12 cached · 4 written · 0 removed
recorded to MLflow: dossier-audit/incident-audit/embed
$ docker exec dossier-index psql -U dossier -d dossier -tA -c "select key, run_id from dossier_index.documents where index = 'masked-tickets' order by key"
PLAY-6001.md|20261011T182937Z-25c2
PLAY-6002.md|20261011T182937Z-25c2
PLAY-6003.md|20261011T182937Z-25c2
PLAY-6004.md|20261011T182937Z-25c2
$ wc -l < embed-calls.jsonl
0
```

3. **The latest run pinned the old declaration.** Adding `Oracle` changed the
   declaration's hash, and a masked index carries a record only from a run
   masked as it masks (R21.17). A run under another declaration holds what
   that masking let through: everything, before `masking:` was declared, or
   every vendor, before `ORGANIZATION` was named. The body chunks were still
   written, masked by the new declaration: masked over masked is a change of
   masking, not of whether it masks (R21.18 row 4). Their texts had not
   changed, so nothing was embedded.
4. **The new run pinned the new declaration.** Its answers came from the
   cache, because the masked text had not changed, and so the record chunks'
   texts had not either. Every vector was cached.

## Task 7 — search for the client (R21.19) **[run · Postgres + Ollama]**

```console
$ : > embed-calls.jsonl
$ $D search masked-tickets "Erika Mustermann complained about CIF 0042-118733" --as incident-response
masked-tickets · 4 documents · as incident-response
1. PLAY-6001.md · PLAY-6001 Settlement export did not run
   PLAY-6001 Settlement export did not run
   Reported by [PERSON_1] on 2026-09-14. Assigned to k.oyelaran. The affected client is [PERSON_2], AHV number [CH_AHV_1], client reference [CLIENT_NUMBER_1]. She called from her phone,…
2. PLAY-6004.md · PLAY-6004 Bonifico sospeso dopo il cambio dell'ora legale
   PLAY-6004 Bonifico sospeso dopo il cambio dell'ora legale
   La cliente [PERSON_1] ha segnalato che il bonifico dal conto [IBAN_CODE_1] era sospeso. Il suo numero AVS è [CH_AHV_1] e il riferimento cliente è [CLIENT_NUMBER_1]. Ha chiamato dal suo telefono, il…
3. PLAY-6003.md · PLAY-6003 Virement bloqué après la mise à jour du service de paiement
   PLAY-6003 Virement bloqué après la mise à jour du service de paiement
   La cliente [PERSON_1] a signalé que son virement depuis le compte [IBAN_CODE_1] était bloqué. Son numéro AVS est le [CH_AHV_1] et sa référence client est [CLIENT_NUMBER_1]. Elle a appelé depuis son…
4. PLAY-6002.md · PLAY-6002 Kassenterminals offline nach Firewall-Änderung
   PLAY-6002 Kassenterminals offline nach Firewall-Änderung
   [PERSON_1] meldete am Montag, dass die orders-api nicht antwortete. Sie ist Kundin mit der Kundennummer [CLIENT_NUMBER_1] und der AHV-Nummer [CH_AHV_1]. Sie war unter ihrer Telefon-Nummer…
recorded to MLflow: dossier-audit/incident-audit/search
$ $P $R/asked.py embed-calls.jsonl
qwen3-embedding:4b-fp16 · 1 texts
  0 of 7  Instruct: Given a question about incidents, retrieve the passages of incident records and documents that answer it Query:[PERSON_1] complained about [CLIENT_NUMBER_1]
1 requests · 1 texts
$ $D search masked-tickets "Erika Mustermann complained about CIF 0042-118733" --as incident-response --json 2>/dev/null \
    | $P -c "import json,sys; r=json.load(sys.stdin); print(r['query']); print([x['document_id'] for x in r['results']])"
[PERSON_1] complained about [CLIENT_NUMBER_1]
['incidents:PLAY-6001.md', 'incidents:PLAY-6004.md', 'incidents:PLAY-6003.md', 'incidents:PLAY-6002.md']
$ wc -l < embed-calls.jsonl
1
```

1. **`[PERSON_1] complained about [CLIENT_NUMBER_1]`**, after the question's
   instruction. The query was masked before it was embedded, searched, printed
   or recorded (R21.19 row 1). The second search asked the model nothing: the
   masked query's vector was cached.
2. **She is `[PERSON_1]` in PLAY-6002, 6003 and 6004. In PLAY-6001,
   `[PERSON_1]` is Hans Muster.** A placeholder is scoped to its note. A
   pseudonym that follows one client across notes needs a secret, and was
   left out (decided 2026-10-02). So `[PERSON_1]` and `[CLIENT_NUMBER_1]` match
   the first person and the client number of any note. Here every note names
   her, so every note is right, for the wrong reason. A search over a masked
   index finds notes that name *a* client. It can never find the notes that
   name *this* one.

```console
$ : > embed-calls.jsonl
$ $D search masked-tickets "Mustermann settlement held" --as incident-response --limit 2
masked-tickets · 2 documents · as incident-response
1. PLAY-6001.md · PLAY-6001 Settlement export did not run
   PLAY-6001 Settlement export did not run
   Reported by [PERSON_1] on 2026-09-14. Assigned to k.oyelaran. The affected client is [PERSON_2], AHV number [CH_AHV_1], client reference [CLIENT_NUMBER_1]. She called from her phone,…
2. PLAY-6002.md · PLAY-6002 Kassenterminals offline nach Firewall-Änderung
   PLAY-6002 Kassenterminals offline nach Firewall-Änderung
   [PERSON_1] meldete am Montag, dass die orders-api nicht antwortete. Sie ist Kundin mit der Kundennummer [CLIENT_NUMBER_1] und der AHV-Nummer [CH_AHV_1]. Sie war unter ihrer Telefon-Nummer…
recorded to MLflow: dossier-audit/incident-audit/search
$ $P $R/asked.py embed-calls.jsonl
qwen3-embedding:4b-fp16 · 1 texts
  0 of 7  Instruct: Given a question about incidents, retrieve the passages of incident records and documents that answer it Query:Mustermann settlement held
1 requests · 1 texts
```

3. **Her surname, as typed.** The masker found no person in three words that
   open with a surname, so there was nothing to mask. While this exercise was
   written, the same words in another order, `settlement held for
   Mustermann`, were masked to `settlement held for [PERSON_1]`. Masking
   replaces every value the masker *detects*, and detection is statistical
   (spec 021, "What masking promises, and what it does not"). `asked.py` says
   `0 of 7` because a canary is a whole value, `Erika Mustermann`, and a part
   of one is not counted. That is why task 5's query looks for parts.

```console
$ $P $R/mlflow_canaries.py http://127.0.0.1:5000
run      dossier-audit/incident-audit/calibrate   calibrate incidents · openai:gpt-5.4-mini
run      dossier-audit/incident-audit/embed       embed masked-tickets 20261011T182729Z
run      dossier-audit/incident-audit/embed       embed masked-tickets 20261011T182914Z
run      dossier-audit/incident-audit/embed       embed masked-tickets 20261011T182941Z
run      dossier-audit/incident-audit/eval        eval 20261011T182627Z-ff8a · openai:gpt-5.4-mini
run      dossier-audit/incident-audit/run         20261011T182627Z-ff8a                        masked/CH_AHV=4 masked/CLIENT_NUMBER=4 masked/EMAIL_ADDRESS=4 masked/IBAN_CODE=4 masked/PERSON=8 masked/PHONE_NUMBER=4
run      dossier-audit/incident-audit/run         20261011T182937Z-25c2                        masked/CH_AHV=4 masked/CLIENT_NUMBER=4 masked/EMAIL_ADDRESS=4 masked/IBAN_CODE=4 masked/PERSON=8 masked/PHONE_NUMBER=4
run      dossier-audit/incident-audit/sync        sync 20261011T182842Z
run      dossier-audit/incident-audit/sync        sync 20261011T182851Z
dataset  incidents
[…the four records of task 4]
traces   dossier-audit/incident-audit/calibrate   20
traces   dossier-audit/incident-audit/embed       1
traces   dossier-audit/incident-audit/eval        4
traces   dossier-audit/incident-audit/run         8
traces   dossier-audit/incident-audit/search      3
         10 of 36 traces hold a placeholder
canaries params 0 of 47 · metrics 0 of 60 · tags 0 of 66 · traces 0 of 36 · dataset records 0 of 4
$ grep -rlaF Mustermann mlflow.db mlartifacts
mlflow.db
mlartifacts/5/7abfc6934c6c4fa7b505210c6503bcf2/artifacts/changes.json
mlartifacts/6/traces/tr-87b9b2ee59ce729562cafe4039c755f9/artifacts/traces.json
$ cat mlartifacts/*/*/artifacts/changes.json 2>/dev/null | grep -i muster
      "key": "Erika-Mustermann-complaint.md",
```

4. **The key, and the surname.** No canary is in any param, metric, tag, trace
   or dataset record. Two things hold part of her name:
   - the sync's `changes.json` names the key `Erika-Mustermann-complaint.md`.
     A key reaches MLflow when it is synced, before any pipeline masks
     anything (R11.6). Spec 021 lists keys under "Not covered by masking at
     all": R21.8 keeps such a key from the model and the index, and only
     renaming it at the source keeps it out of the rest;
   - the surname search's trace, in the database and in its artifact, holds
     the query as typed. The masker did not detect it, and masking promises
     nothing about a value it does not detect. Its recall on real incidents is
     measured on a labelled sample, against a threshold someone agrees to
     (R21.14).

The embed's one trace holds chunk ids and no text. The two searches with her
full name hold the masked query: `10 of 36` is the run's eight and those two.
