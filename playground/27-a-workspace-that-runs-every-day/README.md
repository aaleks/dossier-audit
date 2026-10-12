# 27 · A workspace that runs every day

**You will build:** a workspace that a daily job syncs and runs, and the round
you make of it each morning. Then you will leave it in each untidy state a real
one reaches: a page the sync could not fetch, a run the model never answered, a
cache somebody emptied, a `gc` stopped halfway, a record cut short. Each time
you will read what `status` and `gc` say about it, and clear it up.

**You will learn:** what `status` says about a sync that went wrong, and why it
exits 0 anyway; why `status` and `eval` cannot disagree about a judged field;
how to prove that a `gc` preview deleted nothing; what `gc` keeps of a run it
cannot replay, and why that depends on where the replay stopped; why
`--keep-last 0` is refused before anything is read; why a run directory loses
its manifest last; and what `gc` does with a manifest or a failures file cut
short.

**Uses the stub model, and a website served from your own machine.** Offline,
a few minutes, three terminals. Exercise 09's task 6 and exercise 24 come
first: this one assumes `--keep`, `--keep-last`, the lock and a killed run.

---

## Background, in one paragraph

A workspace a job runs every day is never in the state a tutorial leaves it
in. A vendor takes a page down, the model endpoint is down at six, somebody
empties a cache to free a disk, a reboot cuts a file short. `dossier status`
and `dossier gc` are the two commands for whoever looks after it. `status`
reads the ledger, `runs/` and a gold set, changes nothing, and says what it
found in lines rather than in its exit code: it informs, and the gates are
`eval` and `calibrate` (spec 017). `gc` previews unless it is told `--apply`,
and deletes only what no kept run's replay reads (spec 016). It does not stop
on a run it cannot replay or a record it cannot read. It names it and goes on,
because a clean-up that stops on an untidy workspace never cleans one up.

---

## Setup

Terminal 1, from the repository root. Build the workspace from exercise 07's,
then start the stub with exercise 07's replies, which answer both the
extraction and the judge:

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

Read `sources.yaml` before you go on. The second source, `vendor-runbooks`, is
a website (exercise 18), and `pipelines/runbooks/` exists only so that
`dossier sync runbooks` has a pipeline naming it.

Terminal 2, the vendor's site. Its sitemap names two pages and it serves one:

```bash
.venv/bin/python -m http.server 8098 --bind 127.0.0.1 --directory playground/work/27/site
```

Terminal 3, where every task runs:

```bash
cd playground/work/27
D=../../../.venv/bin/dossier
```

Each `dossier run` below is one morning's job, and the "days" are seconds
apart. Write down each run's id as you make it: the tasks name them as
`<day 1>`, `<day 4>` and so on.

## Task 1 — a page the sync still owes (R17.2, R17.6)

The first morning's job, then the morning check. Watch terminal 2 while the
second sync runs.

```bash
$D sync incident-audit
$D sync runbooks; echo $?
$D run incident-audit
$D status; echo $?
```

**Checkpoint.** `sync runbooks` exits 1 and names `PLAY-7002.html`. `status`
exits 0, and under `vendor-runbooks` it prints

```
    owed PLAY-7002.html, since <when that sync ran>: GET http://127.0.0.1:8098/runbooks/PLAY-7002.html answered 404 File not found
```

- `vendor-runbooks` holds a page, and still says `no complete sync yet`. What
  has not moved, and what would a time in its place have claimed? (R2.8,
  R17.1 row 5.)
- The sync printed the failure once, to a terminal nobody reads at six in the
  morning. Where is it kept after that, and until when? (R2.23.)
- `status` exited 0 with a page owed. A job that checks its exit code never
  hears about it. Write the `grep` that a job would check instead, and run it.
- In a cron line `sync incident-audit && sync runbooks && run incident-audit`,
  what would the vendor's 404 have cost the incident audit? (Exercise 24,
  task 4.)

The vendor publishes the page:

```bash
cp ../../27-a-workspace-that-runs-every-day/resources/later/PLAY-7002.html site/runbooks/
$D sync runbooks; echo $?
$D status
```

**Checkpoint.** The `owed` line is gone, and `vendor-runbooks` says when it
last synced. Look at what terminal 2 logged for this sync: which page was not
asked for again, and why?

Now two questions `status` cannot answer:

```bash
$D status --gold gold/incidents; echo $?
$D status incident-audti; echo $?
```

**Checkpoint.** Both exit 2, and print nothing on standard output. A page owed
was a 0, and a misspelled pipeline is a 2. What is the difference between the
two, for a job reading the exit code? (R17.6.)

## Task 2 — what `eval` will withhold, asked first (R17.7)

`root_cause` is exercise 07's judged field. Copy exercise 07's proposals into
the gold set yourself, as you did there. That copy is you accepting them:

```bash
mkdir -p gold/incidents/samples
cp ../../07-calibrating-a-judge/resources/verified-answers/*.json gold/incidents/
cp ../../07-calibrating-a-judge/resources/calibration-sample/root_cause.jsonl gold/incidents/samples/
cp ../../07-calibrating-a-judge/resources/judge-threshold/judge.yaml gold/incidents/judge.yaml
```

Then ask, score, measure, and ask again:

```bash
$D status incident-audit --gold gold/incidents; echo $?
$D eval incident-audit --gold gold/incidents
$D calibrate incident-audit --gold gold/incidents
$D status incident-audit --gold gold/incidents
$D eval incident-audit --gold gold/incidents
```

**Checkpoint.** The first `status` says `root_cause · withheld:` and a reason,
and exits 0. The first `eval` withholds `root_cause` in the same words. After
`calibrate`, `status` says `root_cause · reportable`, and `eval` prints a
percentage for it.

- `status` and `eval` are two commands. Why can they never disagree about a
  field? (Exercise 07, task 9.)
- In a daily job, does `status --gold` belong before the run or after it? What
  does it cost to ask, in model calls and in records? (R17.5, R11.32.)

## Task 3 — a preview that deletes nothing (R16.5)

Two more mornings. Before the second, an incident note was updated:

```bash
printf '\nUpdate, 2026-03-20: the export is now started by the warehouse load.\n' >> inbox/incidents/PLAY-1002.md
$D sync incident-audit && $D run incident-audit
$D sync incident-audit && $D run incident-audit
```

Three runs now. Preview what `gc` would do, and prove it did nothing:

```bash
$D gc; echo $?
before=$(find .dossier runs -type f | sort | xargs sha256sum | sha256sum)
$D gc --keep-last 1; echo $?
after=$(find .dossier runs -type f | sort | xargs sha256sum | sha256sum)
[ "$before" = "$after" ] && echo "nothing on disk changed"
```

**Checkpoint.** The first preview has nothing to collect. The second would free
two runs and two cache entries, names both runs, ends with `nothing deleted`,
and exits 0. Nothing on disk changed.

- Which two cache entries? Which run was the only one to read each, and why do
  the other answers that run read stay? (R16.3.)
- The size is `0.0 MB`. Count the bytes in the two runs' files alone. In what
  unit is the figure printed, and is it rounded or cut? (R16.5 row 4.)

Apply it:

```bash
$D gc --keep-last 1 --apply; echo $?
ls runs
```

**Checkpoint.** `freed`, with the counts and the size the preview printed, and
one run left.

- If your team compares each morning's run against day 1's with
  `eval --compare`, what should you have run before `--apply`? (R16.6,
  exercise 09 task 6.)

## Task 4 — the morning the model was down (R16.7)

Another note is updated, and this morning nothing answers on the model's port.
A variable set in your shell wins over `.env` (R9.11), so you can make the
endpoint unreachable for one command without stopping the stub:

```bash
printf '\nUpdate, 2026-03-26: the certificate is now renewed by the platform team.\n' >> inbox/incidents/PLAY-1004.md
$D sync incident-audit
DOSSIER_OPENAI_URL=http://127.0.0.1:9/api $D run incident-audit; echo $?
$D status
$D gc; echo $?
$D run --replay runs/<day 4>/; echo $?
$D gc --keep-last 1
```

**Checkpoint.** The run exits 2. `status` says `failures not recorded` for it,
as it did for exercise 24's killed run. `gc` prints, on standard error,

```
  kept as it is: runs/<day 4>/ cannot be replayed: step 'extract' has no cached artifact for 'PLAY-1004.md' …
```

and exits 0. The replay stops with the same words.

- Day 4's run is the latest, so every `gc` keeps it. What would tomorrow's
  daily `gc` do, and the day after's, if a run that cannot be replayed stopped
  `gc`?
- `gc` goes on. Can anything it deletes make day 4's run harder to reproduce
  than it already is?
- `--keep-last 1` would delete three cache entries. Name them. One is the
  answer for `PLAY-1005.md`, a note nobody touched. Why does `gc` not count it
  as one day 4's run needs? What would applying this cost tomorrow, and what
  stops it happening with the default of five? (R16.7 row 2.)

Do not apply it.

## Task 5 — a typo that would delete everything (R16.9)

In the same state:

```bash
$D gc --keep-last 0 --apply; echo $?
$D gc --keep-last -1 --apply; echo $?
ls runs
```

**Checkpoint.** Both exit 2, naming `--keep-last` and `x>=1`. Both runs are
still there.

- Put this beside what `$D gc` printed in task 4. A line on standard error is
  missing here. What does its absence say about when the refusal happened?
- Name the commands that read a pipeline's latest run. What would each do the
  morning after a `--keep-last 0 --apply`?

## Task 6 — a cache somebody emptied (R16.8)

The endpoint is back. Day 5:

```bash
$D run incident-audit
```

The disk fills up, and someone deletes the conversions, because a conversion
can always be made again (R5.9). Count the stage entries before and after:

```bash
find .dossier/cache/stage -type f ! -name '*.meta.json' | wc -l
rm -rf .dossier/cache/convert
$D gc --keep-last 1 --apply; echo $?
find .dossier/cache/stage -type f ! -name '*.meta.json' | wc -l
```

**Checkpoint.** For day 5's run, the `kept as it is` line, then

```
  no cache entry deleted: runs/<day 5>/ stopped before its stages, so the entries it reads cannot be traced
```

Two runs freed, no cache entry, and the same number of stage entries after as
before. Now make the conversions again, and replay:

```bash
$D convert incident-audit
$D run --replay runs/<day 5>/
$D gc
$D gc --apply
```

**Checkpoint.** The replay reproduces all five answers with no model calls.
The `gc` after it collects one cache entry and one replay.

- Day 4's run in task 4 could not be replayed either, and `gc` would still have
  deleted entries. What is different about day 5's, and why does that decide
  whether any entry may go?
- Which part of the cache does `dossier convert` remake byte for byte, and
  which part does no command remake without asking the model?
- Which entry did the last `gc` collect, and what was it waiting for?

## Task 7 — a `gc` stopped halfway (R16.10)

Read `_delete_tree` in `src/dossier/application/gc.py`: the order in which a
run's files are deleted. A `gc --apply` killed partway is hard to time on ten
small files, so make by hand the state one would leave. Day 6, then what a
`gc` stopped one file before the end leaves of day 5:

```bash
$D run incident-audit
find runs/<day 5> -mindepth 1 ! -name manifest.json -delete
find runs/<day 5>
$D gc --keep-last 1; echo $?
$D gc --keep-last 1 --apply
ls runs
```

**Checkpoint.** The preview names `runs/<day 5>/` as a run beyond the latest 1,
and `--apply` finishes it.

Now the other order: what a `gc` that deleted the manifest first would leave.
Day 7:

```bash
$D run incident-audit
rm runs/<day 6>/manifest.json
$D gc --keep-last 1; echo $?
$D status
ls runs
```

**Checkpoint.** `nothing to collect`, and `status` does not mention day 6. `ls`
does.

- Which `gc` will ever delete `runs/<day 6>/`? Who finds it, and how? (R16.2
  row 6.)
- Why does `gc` not treat a directory with no manifest as a run that lost one?
  (R0.11.)

Delete it yourself: `rm -rf runs/<day 6>`.

## Task 8 — a record cut short (R16.11, R4.34)

A run writes its manifest and its failures file whole or not at all (R4.29), so
one cut short was written before R4.29, or edited by a person (R0.11). Make
two. Day 8, then cut day 7's manifest:

```bash
$D run incident-audit
head -c 200 runs/<day 7>/manifest.json > short && mv short runs/<day 7>/manifest.json
$D gc; echo $?
$D status
```

**Checkpoint.** `gc` prints `left as it is: runs/<day 7>/manifest.json cannot
be read:` and the reason, and exits 0. `status` passes over it.

Then cut the latest run's failures file:

```bash
head -c 1 runs/<day 8>/failures.json > short && mv short runs/<day 8>/failures.json
$D gc; echo $?
$D status
```

**Checkpoint.** Day 8 is `kept as it is`, because `failures.json cannot be
read`, followed by task 6's `no cache entry deleted` line. Exit 0. `status`
passes over day 8 too, naming its `failures.json`, and `incident-audit` has
`no run yet`.

- Day 7 is "left as it is" and day 8 is "kept as it is". What does `gc` know
  about each, and what can it not know about day 7?
- Why does a failures file it cannot read mean that no cache entry may go?
- `gc` keeps day 8 as the latest run, and `status` passes it over. What does
  `status` need from the latest run that `gc` does not? (R4.34)

The next morning:

```bash
$D run incident-audit
$D gc --keep-last 1 --apply; echo $?
ls runs
```

**Checkpoint.** The run names day 8 and day 7 before it starts, and goes on.
Day 8 is deleted like any other run. Day 7 is still there, and still named. Read what is left of it if you want to know what it was, then
`rm -rf runs/<day 7>`.

---

## Done when

- you can say what each line `status` printed this week means, which of them a
  job should alert on, and how it finds them;
- you have a `gc` preview you proved deleted nothing, and an `--apply` that
  printed the same counts and size;
- for a run that stopped in its stages, a run whose conversions are gone, a
  manifest cut short and a failures file cut short, you can say what `gc` kept
  and why;
- you know which leftover the next `gc` finishes, and which only a person can.

## Cleaning up

Stop the stub and the site with Ctrl-C in terminals 1 and 2, then:

```bash
rm -rf playground/work/27
```

**Back to:** [the playground index](../README.md).
