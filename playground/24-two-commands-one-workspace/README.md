# 24 · Two commands, one workspace

**You will build:** the daily job spec 015 draws as "cron (daily)", and then
break it the way a real one breaks. A run outlasts its day, a person syncs by
hand beside it, and a run is killed halfway.

**You will learn:** which commands write the workspace and which only read it;
what a second writer is told, and where the details come from; why a refused
command never waits; why a command killed mid-run leaves no lock to clean up;
and what a command that only reads sees of a run that has not finished.

**Uses the stub model**, slowed down with `--delay` as in exercise 22, so that
a run lasts long enough to start a second command beside it. Offline, a few
minutes, three terminals.

---

## Background, in one paragraph

A workspace is one ledger, one snapshot store, one cache and one `runs/`. Two
commands writing it at once can each be right and leave it wrong. `gc --apply`
beside a `run` could delete cache entries the run had just written and no
manifest named yet, and two syncs wrote one ledger. So every command that writes
holds the workspace's lock from before it reads anything to its end: `sync`,
`convert`, `run` (a try and a replay too), `embed`, `gc --apply` and
`review apply` (R20.1). The lock is the operating system's own, on
`.dossier/lock`. Who holds it is written in `.dossier/lock.json` beside it.

---

## Setup

Terminal 1, the stub, taking four seconds over each answer:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/22-what-a-run-costs-and-how-fast-it-goes/resources/replies.json \
  --port 8099 --delay 4
```

Terminal 2, exercise 22's prepared workspace, since its pipeline is already
written:

```bash
mkdir -p playground/work/24/inbox/incidents
cp playground/corpus/incidents/*.md playground/work/24/inbox/incidents/
cp -r playground/22-what-a-run-costs-and-how-fast-it-goes/solution/workspace/. playground/work/24/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/24/.env

cd playground/work/24
D=../../../.venv/bin/dossier
$D sync incident-review
```

Terminal 3: `cd playground/work/24` and set `D` the same way.

## Task 1 — a sync beside a run

Terminal 2: `$D run incident-review`. That is four notes and a summary, at four
seconds each: about twenty seconds. While it runs, in terminal 3:

```bash
$D sync incident-review; echo $?
cat .dossier/lock.json
$D status
```

- What did the sync print, and what exit code did it give? Did it fetch
  anything? Compare `last synced` in the status with the time of the sync in
  the setup.
- Where did the pid and the time come from? Is that pid the process `ps`
  shows running the `run`?
- Why does the refusal not wait for the run to finish? Think of a cron job
  that waits, and the next day's job that starts behind it.

## Task 2 — the commands that only read

While the run is still going, in terminal 3. If it has finished, add a line to
`pipelines/incident-review/prompts/01_extract.md` and start it again: a second
run of the same pipeline is served whole from cache and ends in a second, and
a prompt edit makes it ask afresh (R5.2).

```bash
$D run incident-review --plan; echo $?
$D gc; echo $?
$D gc --apply; echo $?
$D convert incident-review; echo $?
```

- Which of the four ran, and which were refused? Where is the line drawn, and
  why there? Spec 020's table names every command on each side.
- `status`, the plan and the `gc` preview all read the run that is still
  going. What do they say about it? Are they wrong, or right about the
  workspace as the run has left it so far?

## Task 3 — killed halfway

Edit `pipelines/incident-review/prompts/01_extract.md` (add a line), so the
next run asks afresh. Start the run in terminal 2. In terminal 3, wait until
`cat .dossier/lock.json` names a `since` later than the last one, then kill
that pid outright:

```bash
kill -9 <pid>
ls .dossier/
cat .dossier/lock.json
$D status
$D sync incident-review; echo $?
```

- Before the run wrote its own details, what did `lock.json` say? Why may it,
  for a moment, name a writer that has finished (R20.1 row 6)?
- `.dossier/lock` is still there after the kill, and so is `lock.json`, naming
  the dead run. Why did the sync run anyway? Who let the lock go?
- A lock made by creating a file with `O_EXCL` exists only while held. What
  would this task have looked like with one? Spec 020's "Existing options
  considered" says why it was rejected.
- What does `status` say about the killed run's failures, and why does it not
  say "0 failed"?

## Task 4 — one after another

```bash
$D sync incident-review && $D run incident-review; echo $?
```

Both run: a command lets the lock go when it ends. Now the daily job:

```
0 6 * * *  cd /srv/dossier/work && dossier sync incident-review && dossier run incident-review
```

- Yesterday's run is still going at 06:00. What happens to today's sync, and
  to today's run behind the `&&`? What lands in cron's mail?
- What happens the day after, if yesterday's run has finished by then?

---

## What you should now be able to explain

- Why the lock is taken before anything is read, not just before the first
  write.
- Why a second writer is refused rather than made to wait.
- Why the holder's details sit in a file beside the lock and not in it, and
  what a refused command says when that file is missing or half written.
- Why nothing has to be cleaned up after a command is killed.
