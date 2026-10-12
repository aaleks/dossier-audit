# 27 · Solution

Every command below was run against this repository, in order and in one pass,
on 2026-10-11; task 2's in a second pass the same day, from a workspace rebuilt
to where task 2 starts, so its run id and times are that pass's. The output
shown is the output it produced, with the workspace's absolute path cut to `/…/`. A command's standard
error is shown where a terminal shows it. It ran on Windows, where `$D` is
`.venv/Scripts/dossier.exe` and a refused connection reads `[WinError 10061]`;
on Linux or macOS the same line reads `[Errno 111] Connection refused`. The
stub listened on another port than 8099, which no line below shows. Run
ids, times and the hashes of the two notes you edit are that pass's, and yours
will differ.

## Run the prepared answer

Terminal 1, from the repository root: the workspace, then the stub.

```bash
mkdir -p playground/work/27/inbox/incidents playground/work/27/pipelines/runbooks
cp -r playground/07-calibrating-a-judge/solution/workspace/. playground/work/27/
cp -r playground/18-a-website-read-as-documents/solution/workspace/pipelines/site-audit/prompts \
      playground/18-a-website-read-as-documents/solution/workspace/pipelines/site-audit/schemas \
      playground/work/27/pipelines/runbooks/
cp -r playground/27-a-workspace-that-runs-every-day/solution/workspace/. playground/work/27/
cp -r playground/27-a-workspace-that-runs-every-day/resources/site playground/work/27/site
cp playground/corpus/incidents/PLAY-100[1-4].md playground/work/27/inbox/incidents/
cp playground/07-calibrating-a-judge/resources/documents/PLAY-1005.md playground/work/27/inbox/incidents/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/27/.env

.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/07-calibrating-a-judge/resources/replies-judge.json \
  --replies playground/07-calibrating-a-judge/resources/replies.json \
  --port 8099 --log playground/work/27/calls.jsonl
```

Terminal 2, the vendor's site:

```bash
.venv/bin/python -m http.server 8098 --bind 127.0.0.1 --directory playground/work/27/site
```

Terminal 3:

```bash
cd playground/work/27
D=../../../.venv/bin/dossier
$D sync incident-audit
$D sync runbooks
$D run incident-audit
$D status
```

`solution/workspace/` holds only what is new here: `sources.yaml`, with the
second source, and `pipelines/runbooks/pipeline.yaml`. The incident pipeline,
the notes and the replies are exercise 07's, and the runbook pipeline's prompt
and fields are exercise 18's. No gold set is copied: task 2 is where you accept
one.

---

## Task 1 — a page the sync still owes

```console
$ $D sync incident-audit
incidents-manual  0 known · 0 changed · 5 new -> 5 fetched
ledger updated · 5 new snapshots · 0 tombstoned

$ $D sync runbooks; echo $?
vendor-runbooks  0 known · 0 changed · 1 new -> 1 fetched
  vendor-runbooks: PLAY-7002.html failed: GET http://127.0.0.1:8098/runbooks/PLAY-7002.html answered 404 File not found
ledger updated · 1 new snapshots · 0 tombstoned
1 item(s) failed: PLAY-7002.html
1

$ $D run incident-audit
run 20261011T132457Z-fb32 · /…/playground/work/27/runs/20261011T132457Z-fb32/manifest.json
  extract: 5 document(s) · 0 from cache · 0 failed · tokens not reported

$ $D status; echo $?
sources
  incidents-manual · 5 held · 0 tombstoned · last synced 2026-10-11T13:24:53Z
  vendor-runbooks · 1 held · 0 tombstoned · no complete sync yet
    owed PLAY-7002.html, since 2026-10-11T13:24:54Z: GET http://127.0.0.1:8098/runbooks/PLAY-7002.html answered 404 File not found
pipelines
  incident-audit · latest run 20261011T132457Z-fb32 · 5 documents · 0 failed
  runbooks · no run yet
0
```

Terminal 2 logged the sync, in local time where `dossier` writes UTC:

```
127.0.0.1 - - [11/Oct/2026 15:24:54] code 404, message File not found
127.0.0.1 - - [11/Oct/2026 15:24:54] "GET /robots.txt HTTP/1.1" 404 -
127.0.0.1 - - [11/Oct/2026 15:24:54] "GET /sitemap.xml HTTP/1.1" 200 -
127.0.0.1 - - [11/Oct/2026 15:24:55] "GET /runbooks/PLAY-7001.html HTTP/1.1" 200 -
127.0.0.1 - - [11/Oct/2026 15:24:55] code 404, message File not found
127.0.0.1 - - [11/Oct/2026 15:24:55] "GET /runbooks/PLAY-7002.html HTTP/1.1" 404 -
```

A `robots.txt` that is not there allows everything (R1.33). The sitemap named
two pages; one was stored, and one was refused. A fetch that fails does not
stop the sync. The page is recorded as owed, and the sync goes on and exits 1
(R1.9, R2.23).

**`no complete sync yet`.** A source's watermark moves only when a sync handled
every item (R2.8). This one did not, so there is no instant to print. A time
would claim that everything the source had then is held, which is false: one
page is missing. `never synced` would be false as well, and would hide both the
page held and the page owed (R17.1 row 5, R17.2 row 5).

**Where the failure is kept.** In the ledger, as an owed key with the time of
the first sync that failed and the error the last one got (R2.23, R17.2 row 6).
A page refused every night for a week is owed since the first night. The terminal line reaches
cron's mail once. The owed row stays until a sync stores the page, or the
source stops listing it, and every `status` until then prints it (R17.2).

**The `grep`.** `status` exits 0 whatever it finds (R17.6), so a job reads its
lines:

```console
$ $D status | grep -E '^    owed |no complete sync yet'; echo $?
  vendor-runbooks · 1 held · 0 tombstoned · no complete sync yet
    owed PLAY-7002.html, since 2026-10-11T13:24:54Z: GET http://127.0.0.1:8098/runbooks/PLAY-7002.html answered 404 File not found
0
```

`grep` exits 0 when it finds a line, so this is the exit code a job alerts on.
The same pattern can look for `failures not recorded`, for `withheld:`, and for
a count of failed documents that is not 0.

**The cron line.** `sync runbooks` exits 1, so `&&` never starts
`run incident-audit`: a vendor's missing page stops the incident audit. Sync
each pipeline's sources in front of its own run, or join the runbook sync with
`;`. Exercise 24's task 4 is the same chain, stopped by the lock.

The vendor publishes the page:

```console
$ cp ../../27-a-workspace-that-runs-every-day/resources/later/PLAY-7002.html site/runbooks/

$ $D sync runbooks; echo $?
vendor-runbooks  1 known · 0 changed · 1 new -> 1 fetched
ledger updated · 1 new snapshots · 0 tombstoned
0

$ $D status
sources
  incidents-manual · 5 held · 0 tombstoned · last synced 2026-10-11T13:24:53Z
  vendor-runbooks · 2 held · 0 tombstoned · last synced 2026-10-11T13:24:59Z
pipelines
  incident-audit · latest run 20261011T132457Z-fb32 · 5 documents · 0 failed
  runbooks · no run yet

$ $D status | grep -E '^    owed |no complete sync yet'; echo $?
1
```

```
127.0.0.1 - - [11/Oct/2026 15:24:59] code 404, message File not found
127.0.0.1 - - [11/Oct/2026 15:24:59] "GET /robots.txt HTTP/1.1" 404 -
127.0.0.1 - - [11/Oct/2026 15:24:59] "GET /sitemap.xml HTTP/1.1" 200 -
127.0.0.1 - - [11/Oct/2026 15:24:59] "GET /runbooks/PLAY-7002.html HTTP/1.1" 200 -
```

`PLAY-7001.html` was not asked for again: its `<lastmod>` had not moved, so
there was nothing to fetch (R2.1). `PLAY-7002.html` was, and once it was stored
it was owed nothing. Every item handled, the watermark moved.

The two questions `status` cannot answer:

```console
$ $D status --gold gold/incidents; echo $?
--gold gold/incidents names a gold set, and one gold set can serve several pipelines (R3.7): name the pipeline its judges are checked for, as `dossier status PIPELINE --gold gold/incidents`
2

$ $D status incident-audti; echo $?
no pipeline 'incident-audti': expected /…/playground/work/27/pipelines/incident-audti/pipeline.yaml
2
```

Both lines are on standard error, and nothing is on standard output. A 0 says
`status` answered, and what it found is in its lines, however bad. A 2 says it
could not answer, so there are no lines to read: the job itself is wrong, and
no `grep` of an empty output can tell that from a clean workspace (R17.6 rows
3 and 4).

## Task 2 — what `eval` will withhold, asked first

The four proposals, the calibration sample and the threshold are exercise 07's,
copied as they ship: that copy is the acceptance the README asks of you.

```console
$ mkdir -p gold/incidents/samples
$ cp ../../07-calibrating-a-judge/resources/verified-answers/*.json gold/incidents/
$ cp ../../07-calibrating-a-judge/resources/calibration-sample/root_cause.jsonl gold/incidents/samples/
$ cp ../../07-calibrating-a-judge/resources/judge-threshold/judge.yaml gold/incidents/judge.yaml

$ $D status incident-audit --gold gold/incidents; echo $?
sources
  incidents-manual · 5 held · 0 tombstoned · last synced 2026-10-11T18:47:02Z
  vendor-runbooks · 1 held · 0 tombstoned · no complete sync yet
    owed PLAY-7002.html, since 2026-10-11T18:47:03Z: GET http://127.0.0.1:8098/runbooks/PLAY-7002.html answered 404 File not found
pipelines
  incident-audit · latest run 20261011T184704Z-6070 · 5 documents · 0 failed
judged fields · incident-audit against gold/incidents
  root_cause · withheld: never measured -- run `dossier calibrate`
0

$ $D eval incident-audit --gold gold/incidents
5 documents · 4 fields · overall 100.0%
  loss_amount        100.0%
  resolution_date    100.0%
  severity           100.0%
  affected_systems   100.0%
  root_cause             -- never measured -- run `dossier calibrate`

$ $D calibrate incident-audit --gold gold/incidents
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8

$ $D status incident-audit --gold gold/incidents
sources
  incidents-manual · 5 held · 0 tombstoned · last synced 2026-10-11T18:47:02Z
  vendor-runbooks · 1 held · 0 tombstoned · no complete sync yet
    owed PLAY-7002.html, since 2026-10-11T18:47:03Z: GET http://127.0.0.1:8098/runbooks/PLAY-7002.html answered 404 File not found
pipelines
  incident-audit · latest run 20261011T184704Z-6070 · 5 documents · 0 failed
judged fields · incident-audit against gold/incidents
  root_cause · reportable

$ $D eval incident-audit --gold gold/incidents
5 documents · 5 fields · overall 100.0%
  loss_amount        100.0%
  resolution_date    100.0%
  severity           100.0%
  affected_systems   100.0%
  root_cause         100.0%   (4 judged)
```

The reason is the same words in both places, "never measured", because
`status` asks the function `eval` asks rather than a copy of it (R17.7,
exercise 07's task 9). Asking costs nothing: `status` changes no file, records
nothing and asks no model (R17.5, R11.32), so a daily job can ask before its run
and again after it.

Neither `eval` nor `calibrate` writes under `runs/` or into the stage or convert
caches: `eval` caches its judge's verdicts under `.dossier/cache/judge/`, which
`gc` never touches, and `calibrate` writes under `gold/`. So this task changes
nothing the transcripts of tasks 3 to 8 show.

## Task 3 — a preview that deletes nothing

```console
$ printf '\nUpdate, 2026-03-20: the export is now started by the warehouse load.\n' >> inbox/incidents/PLAY-1002.md

$ $D sync incident-audit && $D run incident-audit
incidents-manual  5 known · 1 changed · 0 new -> 5 fetched
      PLAY-1002.md  950d8ed7fbe310505a8d01cb02233239e3524bd445022b892caa7d6b1ab60007 -> 45bbbb16d7d29c5cd3b7fed08842ab844519bdd509aa2ed61b64ca5b2f3fc164
ledger updated · 1 new snapshots · 0 tombstoned
warning: the source has moved since run 20261011T132457Z-fb32: PLAY-1002.md re-snapshotted
run 20261011T132505Z-01ab · /…/playground/work/27/runs/20261011T132505Z-01ab/manifest.json
  extract: 5 document(s) · 4 from cache · 0 failed · tokens not reported

$ $D sync incident-audit && $D run incident-audit
incidents-manual  5 known · 0 changed · 0 new -> 5 fetched
ledger updated · 0 new snapshots · 0 tombstoned
run 20261011T132508Z-5b1d · /…/playground/work/27/runs/20261011T132508Z-5b1d/manifest.json
  extract: 5 document(s) · 5 from cache · 0 failed

$ $D gc; echo $?
nothing to collect
0

$ before=$(find .dossier runs -type f | sort | xargs sha256sum | sha256sum)
$ $D gc --keep-last 1; echo $?
would free 0.0 MB: 2 runs, 0 tries, 0 replays, 2 cache entries
  runs/20261011T132457Z-fb32/  incident-audit, beyond the latest 1
  runs/20261011T132505Z-01ab/  incident-audit, beyond the latest 1
nothing deleted: run `dossier gc --apply` to delete it
0
$ after=$(find .dossier runs -type f | sort | xargs sha256sum | sha256sum)
$ [ "$before" = "$after" ] && echo "nothing on disk changed"
nothing on disk changed
```

The first preview keeps five runs of each pipeline, so all three stay, and
every entry is read by one of them. The second keeps one. Every file under
`.dossier/` and `runs/` holds the bytes it held before it, and none was added
(R16.5 row 1). A preview takes no lock either: only `--apply` writes (R20.1).

**The two cache entries** are `PLAY-1002.md`'s answer and its conversion, from
before the update. Day 1 was the only run to read them: days 2 and 3 read the
new snapshot's. The other four answers day 1 read are each one entry, which
days 2 and 3 read as well, and the kept day 3 needs them. An entry goes only
when no kept run's replay reads it, whichever run wrote it (R16.3 row 2). The
other four conversions stay for a second reason too: the ledger holds their
snapshots now, and the next run reads them (R16.3 row 4).

**`0.0 MB`.**

```console
$ find runs/20261011T132457Z-fb32 runs/20261011T132505Z-01ab -type f | xargs cat | wc -c
29910
```

The two runs' files alone are 29 910 bytes, before the two entries. The figure
is in MB of 10^6 bytes, as a disk's free space is reported, rounded to one
decimal (R16.5 row 4). Anything under 50 000 bytes prints `0.0`. On markdown
notes that is most days, which is why the size is never printed alone: the
counts beside it say what goes.

```console
$ $D gc --keep-last 1 --apply; echo $?
freed 0.0 MB: 2 runs, 0 tries, 0 replays, 2 cache entries
  runs/20261011T132457Z-fb32/  incident-audit, beyond the latest 1
  runs/20261011T132505Z-01ab/  incident-audit, beyond the latest 1
0

$ ls runs
20261011T132508Z-5b1d
```

The counts, the size and the run lines are the preview's, with `freed` for
`would free` (R16.5 row 2). One decision makes both, so what you read in the
preview is what `--apply` does.

**Before `--apply`**, if day 1 is your baseline: `dossier gc --keep
20261011T132457Z-fb32`. It writes `runs/20261011T132457Z-fb32/keep`, deletes
nothing, and every later `gc` keeps that run and the two entries it read
(R16.6, exercise 09 task 6). A `--label` cannot do it: the label lives only in
MLflow, and `gc` reads nothing back from there.

## Task 4 — the morning the model was down

```console
$ printf '\nUpdate, 2026-03-26: the certificate is now renewed by the platform team.\n' >> inbox/incidents/PLAY-1004.md

$ $D sync incident-audit
incidents-manual  5 known · 1 changed · 0 new -> 5 fetched
      PLAY-1004.md  d7c5317a23938586cd2ce4d2778373d32693309ab91445e62120bbaa83211ac8 -> 5a3455a1542c99e73262865431b624b0ab90cbdb053929307a2166b6cec5da77
ledger updated · 1 new snapshots · 0 tombstoned

$ DOSSIER_OPENAI_URL=http://127.0.0.1:9/api $D run incident-audit; echo $?
warning: the source has moved since run 20261011T132508Z-5b1d: PLAY-1004.md re-snapshotted
incident-audit: POST http://127.0.0.1:9/api/chat/completions failed: [WinError 10061] No connection could be made because the target machine actively refused it (after 3 attempts)
2

$ $D status
sources
  incidents-manual · 5 held · 0 tombstoned · last synced 2026-10-11T13:25:11Z
  vendor-runbooks · 2 held · 0 tombstoned · last synced 2026-10-11T13:24:59Z
pipelines
  incident-audit · latest run 20261011T132513Z-abe2 · 5 documents · failures not recorded
  runbooks · no run yet

$ $D gc; echo $?
  kept as it is: runs/20261011T132513Z-abe2/ cannot be replayed: step 'extract' has no cached artifact for 'PLAY-1004.md' at d2fb0c53be0a...; this run cannot be reproduced from this workspace, and nothing has been substituted for it.
nothing to collect
0

$ $D run --replay runs/20261011T132513Z-abe2/; echo $?
step 'extract' has no cached artifact for 'PLAY-1004.md' at d2fb0c53be0a...; this run cannot be reproduced from this workspace, and nothing has been substituted for it.
2
```

The run wrote its manifest before it asked anything, served `PLAY-1001.md` to
`PLAY-1003.md` from the cache, and stopped at `PLAY-1004.md`, the first note it
had to ask about. A refused connection is retried twice and then stops the command in
one line (R9.17 row 4, R9.20). It wrote no `failures.json`, so `status` says
`failures not recorded`, not `0 failed`: exercise 24's task 3, and R17.3 row 5.

**If it stopped `gc`.** Day 4's run is the latest, and the latest is always
kept, so every `gc` from now on would meet it. Stopped, the daily `gc` would
fail tomorrow, and the day after, until a person deleted the run by hand. A run
interrupted with Ctrl-C would do the same (R16.7).

**Going on makes nothing worse.** The run was already irreproducible: no entry
holds an answer for `PLAY-1004.md` under its key, because the model was never
asked. Nothing `gc` deletes can change that. What `gc` guarantees is that a run
which replayed before it replays after it (R16.1), and day 4's did not replay
before it. So it is named, on standard error, and `gc` goes on with exit 0.

```console
$ $D gc --keep-last 1
  kept as it is: runs/20261011T132513Z-abe2/ cannot be replayed: step 'extract' has no cached artifact for 'PLAY-1004.md' at d2fb0c53be0a...; this run cannot be reproduced from this workspace, and nothing has been substituted for it.
would free 0.0 MB: 1 run, 0 tries, 0 replays, 3 cache entries
  runs/20261011T132508Z-5b1d/  incident-audit, beyond the latest 1
nothing deleted: run `dossier gc --apply` to delete it
```

**The three entries** are `PLAY-1004.md`'s old answer and its old conversion,
which only day 3 read, and `PLAY-1005.md`'s answer. `gc` finds what a kept run
needs by tracing its replay. Day 4's replay read all five conversions, since a
replay reads every conversion before its first stage, then the answers for
`PLAY-1001.md` to `PLAY-1003.md`, and stopped at `PLAY-1004.md`. It never
reached `PLAY-1005.md`, so nothing kept is known to read that answer. What the
replay read before it stopped is kept, and only that (R16.7 row 2).

Applied, it would cost a model call tomorrow: the next run would ask about
`PLAY-1005.md` again, though its note never changed. With the default of five,
day 3's run is kept, its replay reads that answer, and it stays. Keeping more
than one run is what protects the answers a stopped run never reached.

## Task 5 — a typo that would delete everything

```console
$ $D gc --keep-last 0 --apply; echo $?
Usage: dossier gc [OPTIONS]
Try 'dossier gc --help' for help.
┌─ Error ─────────────────────────────────────────────────────────────────────┐
│ Invalid value for '--keep-last': 0 is not in the range x>=1.                │
└─────────────────────────────────────────────────────────────────────────────┘
2

$ $D gc --keep-last -1 --apply; echo $?
Usage: dossier gc [OPTIONS]
Try 'dossier gc --help' for help.
┌─ Error ─────────────────────────────────────────────────────────────────────┐
│ Invalid value for '--keep-last': -1 is not in the range x>=1.               │
└─────────────────────────────────────────────────────────────────────────────┘
2

$ ls runs
20261011T132508Z-5b1d
20261011T132513Z-abe2
```

**The missing line** is task 4's `kept as it is: runs/20261011T132513Z-abe2/`.
`gc` prints it after it has read every manifest and traced every kept run's
replay. Here it never got that far: the value was refused while the command
line was read, before the workspace's lock was asked for, before `runs/` was
listed (R16.9).

**What reads the latest run.** `eval` scores it, `status` names it, and
`embed` carries its answers into the index (R18.8). After `--keep-last 0 --apply`, the next `eval` would say there is no
run to score, and every run not pinned would be gone, with the cache entries
only they read. A negative is refused the same way: it is not "keep none"
either.

## Task 6 — a cache somebody emptied

```console
$ $D run incident-audit
run 20261011T132526Z-a5a4 · /…/playground/work/27/runs/20261011T132526Z-a5a4/manifest.json
  extract: 5 document(s) · 4 from cache · 0 failed · tokens not reported

$ find .dossier/cache/stage -type f ! -name '*.meta.json' | wc -l
6

$ rm -rf .dossier/cache/convert

$ $D gc --keep-last 1 --apply; echo $?
  kept as it is: runs/20261011T132526Z-a5a4/ cannot be replayed: 20261011T132526Z-a5a4 cannot be reproduced: PLAY-1001.md: no cached conversion for snapshot 6bdb8cad3ebd... by markdown-text 1.0.0 PLAY-1002.md: no cached conversion for snapshot 45bbbb16d7d2... by markdown-text 1.0.0 PLAY-1003.md: no cached conversion for snapshot 9c5d76c19307... by markdown-text 1.0.0 PLAY-1004.md: no cached conversion for snapshot 5a3455a1542c... by markdown-text 1.0.0 PLAY-1005.md: no cached conversion for snapshot 4a3401534177... by markdown-text 1.0.0 Nothing has been substituted.
  no cache entry deleted: runs/20261011T132526Z-a5a4/ stopped before its stages, so the entries it reads cannot be traced
freed 0.0 MB: 2 runs, 0 tries, 0 replays, 0 cache entries
  runs/20261011T132508Z-5b1d/  incident-audit, beyond the latest 1
  runs/20261011T132513Z-abe2/  incident-audit, beyond the latest 1
0

$ find .dossier/cache/stage -type f ! -name '*.meta.json' | wc -l
6
```

Day 5 asked one question, about `PLAY-1004.md`'s new snapshot. The six stage
entries are the five answers day 5 read and `PLAY-1004.md`'s old answer, which
only day 3 read.

**What is different from day 4.** Day 4's replay reached its stages, so what it
read was traced, and the rest could be judged. Day 5's replay stopped before it
read a single stage key: a replay reads every conversion first (R4.7), and
there were none. So which answers day 5 needs is unknown, and `gc` deletes no
entry from either cache until every kept run traces (R16.8 rows 1 and 3). Runs
are still deleted, since no kept run reads them. That is why the two runs went
and the six entries stayed.

**What each command remakes.** A conversion is remade byte for byte by
`dossier convert`, with no model (R5.9). An answer is a model's, and only the
model makes it again. Collected now, day 5's answers would turn a run one
command away from replaying into one that never replays again.

```console
$ $D convert incident-audit
incidents-manual  5 held · 5 converted · 0 cached
cache updated · 5 converted · 0 cached

$ $D run --replay runs/20261011T132526Z-a5a4/
replayed 20261011T132526Z-a5a4 · incident-audit
  extract: 5 artifact(s) from cache
5 artifact(s) reproduced · no model calls · written to runs/20261011T132526Z-a5a4/replays/20261011T132528Z-3cec/

$ $D gc
would free 0.0 MB: 0 runs, 0 tries, 1 replay, 1 cache entry
nothing deleted: run `dossier gc --apply` to delete it

$ $D gc --apply
freed 0.0 MB: 0 runs, 0 tries, 1 replay, 1 cache entry
```

The run was as `gc` found it: one deterministic command from replaying (R16.8
row 2). The entry collected now is `PLAY-1004.md`'s old answer. Only day 3,
deleted above, read it. It waited for a `gc` that could trace day 5 and see
that day 5 does not read it. The replay is the one just made: byte copies of
entries day 5 reproduces at any time (R16.4).

## Task 7 — a `gc` stopped halfway

`_delete_tree` deletes a run's files deepest first, skipping `manifest.json`,
then the manifest, then the directory. However the file system lists them, the
manifest is the last file of the run to go (R16.10).

```console
$ $D run incident-audit
run 20261011T132532Z-18b3 · /…/playground/work/27/runs/20261011T132532Z-18b3/manifest.json
  extract: 5 document(s) · 5 from cache · 0 failed

$ find runs/20261011T132526Z-a5a4 -mindepth 1 ! -name manifest.json -delete

$ find runs/20261011T132526Z-a5a4
runs/20261011T132526Z-a5a4
runs/20261011T132526Z-a5a4/manifest.json

$ $D gc --keep-last 1; echo $?
would free 0.0 MB: 1 run, 0 tries, 0 replays, 0 cache entries
  runs/20261011T132526Z-a5a4/  incident-audit, beyond the latest 1
nothing deleted: run `dossier gc --apply` to delete it
0

$ $D gc --keep-last 1 --apply
freed 0.0 MB: 1 run, 0 tries, 0 replays, 0 cache entries
  runs/20261011T132526Z-a5a4/  incident-audit, beyond the latest 1

$ ls runs
20261011T132532Z-18b3
```

A directory holding `manifest.json` is a run (R16.2). With only its manifest
left, day 5 is still a run of `incident-audit`, still beyond the latest one,
and the next `gc` finishes what the stopped one began (R16.10 row 2). Nothing
had to be noticed, and nothing was done by hand.

The other order:

```console
$ $D run incident-audit
run 20261011T132535Z-99cd · /…/playground/work/27/runs/20261011T132535Z-99cd/manifest.json
  extract: 5 document(s) · 5 from cache · 0 failed

$ rm runs/20261011T132532Z-18b3/manifest.json

$ $D gc --keep-last 1; echo $?
nothing to collect
0

$ $D status
sources
  incidents-manual · 5 held · 0 tombstoned · last synced 2026-10-11T13:25:11Z
  vendor-runbooks · 2 held · 0 tombstoned · last synced 2026-10-11T13:24:59Z
pipelines
  incident-audit · latest run 20261011T132535Z-99cd · 5 documents · 0 failed
  runbooks · no run yet

$ ls runs
20261011T132532Z-18b3
20261011T132535Z-99cd

$ rm -rf runs/20261011T132532Z-18b3
```

**No `gc` will ever delete it.** A directory with no manifest is not a run, and
`gc` neither keeps nor deletes what it cannot account for (R16.2 row 6).
`status` does not count it either (R17.3 row 4). Only someone listing `runs/`
finds it, and only by comparing what is there with what the tools name. Every
`gc` interrupted that way would leave another, and the space it was asked to
free would be held for good.

**Why `gc` does not guess.** `runs/` is edited by people (R0.11): a reviewer's
notes, a copy kept for an audit. A directory there with no manifest may be one
of those, and `gc` has no way to tell it from a run that lost its manifest. So
the manifest goes last, and the question never arises.

## Task 8 — a record cut short

```console
$ $D run incident-audit
run 20261011T132538Z-8fec · /…/playground/work/27/runs/20261011T132538Z-8fec/manifest.json
  extract: 5 document(s) · 5 from cache · 0 failed

$ head -c 200 runs/20261011T132535Z-99cd/manifest.json > short && mv short runs/20261011T132535Z-99cd/manifest.json

$ $D gc; echo $?
  left as it is: runs/20261011T132535Z-99cd/manifest.json cannot be read: Unterminated string starting at: line 7 column 5 (char 182)
nothing to collect
0

$ $D status
sources
  incidents-manual · 5 held · 0 tombstoned · last synced 2026-10-11T13:25:11Z
  vendor-runbooks · 2 held · 0 tombstoned · last synced 2026-10-11T13:24:59Z
pipelines
  passed over: runs/20261011T132535Z-99cd/manifest.json cannot be read: Unterminated string starting at: line 7 column 5 (char 182)
  incident-audit · latest run 20261011T132538Z-8fec · 5 documents · 0 failed
  runbooks · no run yet

$ head -c 1 runs/20261011T132538Z-8fec/failures.json > short && mv short runs/20261011T132538Z-8fec/failures.json

$ $D gc; echo $?
  left as it is: runs/20261011T132535Z-99cd/manifest.json cannot be read: Unterminated string starting at: line 7 column 5 (char 182)
  kept as it is: runs/20261011T132538Z-8fec/ cannot be replayed: failures.json cannot be read: Expecting value: line 1 column 2 (char 1)
  no cache entry deleted: runs/20261011T132538Z-8fec/ stopped before its stages, so the entries it reads cannot be traced
nothing to collect
0
```

**Left, and kept.** A manifest that cannot be read says nothing of its run, not
even its pipeline. `gc` cannot count day 7 among `incident-audit`'s runs, so it
cannot keep it or delete it: it is left as a directory with no manifest is, and
named so that someone can look (R16.11 row 1). `status` passes over it the same
way (R4.30). Day 8's manifest reads, so day 8 is a run of `incident-audit`, the
latest, and kept as any latest run is.

**Why no entry goes.** A replay needs the run's failures to know which answers
the run never wrote, and asks for none of them (R4.28). Without them it cannot
start its stages, which is task 6's case: the entries day 8 reads cannot be
traced, so none is deleted (R16.11 row 2, R16.8). Without R16.11, either file
cut short would stop `gc` with a traceback, and nothing would be deleted until
a person found the file.

The next morning:

```console
$ $D run incident-audit
run 20261011T132543Z-27a4 · /…/playground/work/27/runs/20261011T132543Z-27a4/manifest.json
  extract: 5 document(s) · 5 from cache · 0 failed

$ $D gc --keep-last 1 --apply; echo $?
  left as it is: runs/20261011T132535Z-99cd/manifest.json cannot be read: Unterminated string starting at: line 7 column 5 (char 182)
freed 0.0 MB: 1 run, 0 tries, 0 replays, 0 cache entries
  runs/20261011T132538Z-8fec/  incident-audit, beyond the latest 1
0

$ ls runs
20261011T132535Z-99cd
20261011T132543Z-27a4

$ rm -rf runs/20261011T132535Z-99cd

$ ls runs
20261011T132543Z-27a4
```

Day 8 aged out like any run: its manifest names its pipeline, and day 9 is the
latest. Day 7 is named on every `gc` until a person deals with it, which is the
point of naming it.

---

## What to take to your own project

- A check that informs exits 0 and says what it found in lines. A gate exits
  non-zero. Keep the two apart, and let the job that wants an alert read the
  lines.
- Keep what a failure leaves in the state, not in the output of the command
  that failed. The owed page outlived the terminal it was printed to.
- A clean-up that deletes must preview by default, and the preview and the
  delete must come from one decision.
- Decide what may go by tracing what a kept thing actually reads. Where the
  trace stops early, keep what it reached; where it cannot start, keep
  everything that cannot be made again.
- Delete the file that makes a thing a thing last, so an interruption leaves
  something the next run recognises.
- Never stop a clean-up on a record you cannot read. Name it, leave it, and go
  on.
