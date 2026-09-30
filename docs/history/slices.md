# What each slice changed

The story of `dossier`, one paragraph or a few per slice, **newest first**: what
landed, why it was needed, and what a live check found that the default suite
could not. The specs say what is true; this says how it came to be.

It lived in `CLAUDE.md` until 2026-09-24 and moved here unchanged, because
`CLAUDE.md` is read at the start of every session and had grown past 30 KB of
it. A slice that lands adds its paragraph at the top.

Rule ids below are the ids at the time of writing. An id that has since been
superseded is still correct history, and `specs/` names what replaced it.

---

`sync` and `convert` say they recorded (R11.4 rows 4 to 6). They were the last
two commands that recorded to MLflow without saying so: `run`, `eval`,
`calibrate` and, since R11.28 row 6, `gc` end with
`recorded to MLflow: <experiment>`. Now every command that records says where,
and one that records nothing says nothing.

A comparison that lost a document says so on its record (R11.29, R11.30).
R7.55 marks a document `b` failed and `a` answered as a regression, and keeps it
out of `dossier.regressed`, which names fields. That left the terminal and
`deltas.md` as the only places the loss appeared: the record was tagged
`dossier.regressed` empty, as a comparison that changed nothing is, and its
description said `regressed nothing` beside the marked document. So a search for
regressions missed the worst one. `dossier.lost` now names those documents,
present and empty when there are none, and the description's `regressed` line
names them after the fields: `regressed INC-4822 (failed at extract)`. One
decision, `lost_documents`, is behind the marker, the tag and the line, so they
cannot disagree. The live check ran exercise 06's failed `PLAY-1004.md` against
the local MLflow in both directions and read both records back. The lost
comparison was tagged `PLAY-1004.md`, and the recovered one was tagged present
and empty, with `regressed nothing`. The server kept the empty tag, and the
filter ``tags.`dossier.lost` != ''`` found the lost comparison alone. While
writing the rule, R11.12 row 3 turned out to spell the line
`regressed: affected_systems`, which no code had ever written. It now reads as
shipped.

Two things the `gc` live check showed (R11.28 rows 6 and 7, R0.15). `gc --apply`
now ends with `recorded to MLflow: dossier-audit/gc`, as `eval` and `calibrate`
end with theirs; `sync` and `convert` still print no such line, which is the
same gap in two older commands. And run ids now sort in the order runs started.
A run is filed as `<second>-<suffix>`, and every reader of "the latest run"
takes the last by name, but the suffix was drawn at random, so two runs within
one second sorted by chance. When the second already holds a run, the suffix is
now the one after the last used in it (`4f1a` then `4f1b`, `ffff` then `ffff0`),
and the id keeps its form. A try is ordered among tries. Two processes starting
at the same moment are still not ordered: neither is filed when the other looks.

Reclaiming space: `dossier gc` (spec 016, R11.28). Nothing in `dossier` deleted
anything. Runs, tries, replays and the stage and convert caches only grew, and
"the cache is safe to delete" (R5.9) is true for the next run only: a replay and
an eval reproduce a past run from its manifest and the cache (R4.7, R7.10). So
`gc` keeps the latest five runs of each pipeline and every run holding a `keep`
file. It deletes every other run, every try and every replay, and the cache
entries no kept run's replay reads, and it previews unless given `--apply`. A
run's `--label` could not be the pin, because it lives only in MLflow, which
`gc` never reads back. What a kept run needs is found by running that run's own
replay through a cache that notes each key and refuses every write, so no
second computation of the keys can drift from the one a replay makes. It works
across every pipeline, which made it the first command with no pipeline: its
record lands in `dossier-audit/gc` with `dossier.pipeline` present and empty
(all decided by `a.aleks` on 2026-09-30).

Three things were found on the way. R16.2's counter-example, three runs and N
five, caught a negative slice that kept only the last two. A mutant that forgot
every conversion a kept run read passed R16.3's first six rows, because in each
of them the held-now exception kept those conversions anyway, so row 7 was added
before the code: a kept run that read a snapshot the ledger no longer holds. And
a test fixture built with `execute` alone had no snapshots, so its "kept run"
could never replay, and a plan over it proved nothing. The tests now build their
workspaces through the CLI. `apply_plan` deletes directories before cache
entries, so an interruption leaves only entries no run names, for the next
`gc`, never a run whose entries are gone. A kept run that already cannot be
replayed, a Ctrl-C'd latest run, is named and kept as it is, rather than
blocking every `gc` (R16.7).

The live check on a copy of exercise 06's workspace, against the real MLflow,
read back both records with their counts and `collected.json`, and the kept run
still replayed and scored. Two things it showed are not changed here. Unlike
`run` and `eval`, `gc --apply` prints no `recorded to MLflow: …` line, and no
rule asks for one. And runs started within one second, which only a stub model
manages, sort by their random suffix, so "the latest run" `eval` picks (R0.8),
and the runs `gc` keeps, can follow the suffix rather than the order they were
made. Exercise 09 task 6 walks through a preview, a pin, `--apply` and the
replays after it.

Comparing runs with a failed document (R7.53, R7.54, R7.55, R11.27). A
`/verify` on the day's second batch of rules found that R4.28 had changed
more than it meant to. Letting a replay reproduce a failure let `eval --compare`
through too, where it had stopped, exit 2. It scored the run that failed a
document over three documents and the other over four, and flagged each field
the failed document had been right on: `resolution_date 75.0% 66.7% -8.3 <-
regression`, with nothing changed but the failure, and the failure named nowhere.
R7.8's own title, "over the same documents", was checked against the manifests
alone, and a failure got past it. The same review found `eval` naming a document
as `not scored` when a step *after* the scored one had failed it, though it was
scored, and naming a document twice when two steps failed it. Mutating R4.28's
replay to look up the cache before trusting a recorded failure survived the
whole suite, so that claim is still owed a row.

`dossier.domain.scoring.unscored` now decides what a run left unscored: the
documents the scored step has no answer for, each once, at its first failure up
to the scored step (R7.53). `eval` names those, and `--compare` scores both runs
without any document either left unscored, so every delta is over documents both
answered (R7.54). Its headline says `3 of 4 documents`. Beneath the fields it
names each one with its run, step and reason, marked `<- regression` when `b`
lost a document `a` answered (R7.55), which is `a.aleks`'s call over naming it
alone. Refusing the comparison was the other safe choice, and it would have
made a configuration that always fails one document impossible to pass through
the gate. The record says the same: `a/failed` and `b/failed`, the description's
count, and the lines in `deltas.md` (R11.27). The live check read them back from
MLflow. It also showed the description's `regressed nothing` beside a marked
line, because `dossier.regressed` names fields only, as decided.

A run with a failed document replays and scores (R4.27, R4.28, R7.52). One
failed document made a whole run unscorable. `dossier eval` scores a replay
(R7.10), and the replay stopped on the failed document's missing entry, exit 2,
because nothing said it had failed rather than been lost. R7.50 row 6, "a failed
document is reported as failed, not scored", was proved on the scorer alone and
never reached through the CLI. It was the R3.16 pattern again. Exercise 06 had
left the question open on purpose, "refuse the lot" or "score the three and say
so", to be settled by a rule in spec 007 or not at all.

A run now records each unit it failed in `runs/<id>/failures.json` when it ends
(R4.27). That is `[]` when nothing failed, and none when the run stopped. It is
not in the manifest, which R4.8 keeps a function of resolution. It is not beside
the artifact either, where R0.11 row 4 says nothing stands in for a failed one.
A replay reproduces a recorded failure instead of looking for its entry. It
skips what the run skipped after it, and still stops on an entry that is missing
without a record (R4.28), so a cleared cache never reads as a failed model.
`eval` scores the rest, counts the failures in its headline, names each one, and
records a `failed` metric (R7.52). `a.aleks` chose the headline count over naming
the failures beneath alone, and over scoring them as wrong. Exercise 06 shows
why it matters: its three surviving documents score `overall 100.0% · 1 failed`,
and without the count that would read as a perfect run.

Two checks of the checks along the way. A mutant `/tdd` reported as surviving
had never been applied: the scripted edit lost its backslashes. Applied with the
Edit tool, the test caught it. And the replay now mirrors R6.13 and R6.28. Until
failures could be reproduced, a replay never reached a step after one, so it had
never needed to.

---

A failed document is reported with its reason (R6.31 – R6.33). `dossier run`
printed `    extract failed on INC-4822`, and never why. The reason reached the
MLflow trace, so with tracking off it was printed nowhere. The line now ends
with the reason, on one line. A validation failure's reason is what was wrong,
each of pydantic's errors as `location: message`, every one of them. It has no
pydantic header, no documentation link, and not the document's name the line
already gives. Exercise 06's never-valid reply now reads
`PLAY-1004.md: no valid output after 2 attempts: findings: Extra inputs are not
permitted; fields: Field required`. The retry prompt and each attempt's span
keep pydantic's full text, so the model is shown what it always was.
Discovering this found that a page-by-page document's reason never said which
page failed. Each page's reason now starts with its name, as `dossier eval`
names the page of a miss (R7.48). `a.aleks` chose the concise reason over
pydantic's text or the model's reply, and every error over the first and a
count.

Three older tests had checked the document's name inside the error, as a
stand-in for other things: R11.1's "the trace names the error", and R0.3 and
R6.9's "this document failed". They now check those directly. Re-running
exercise 06 for its transcript also corrected the transcript's count of five
calls, which it had given as six.

---

A call whose every input is empty is never made (R6.28 – R6.30). The same
defect had been closed one shape at a time: a model asked about an input that
came out empty, and the answer cached under the key of nothing. R6.13, R6.21,
R3.16 and R3.19 each closed one shape, each after the fact. The guard is at the
call, where the next shape will arrive. Discovering it turned up two more live
shapes:

- an `aggregate` or `per_group` step whose every member failed earlier was
  asked about `<extract></extract>`;
- an empty file was asked about as an empty `<document>`.

The first is now a skip, since its cause is listed once already (R6.28). The
second, and anything else whose every input is empty, fails the document,
naming the inputs (R6.29). `a.aleks` chose to fail rather than skip, and to
count a document's own empty text. A present, empty document renders as a
wrapper, not the empty string, so the check reads each input unwrapped. It runs
before the cache, so an answer cached about nothing is never served again, and
replay makes the same decision, reproducing the failure.

`_fixtures.md` said `pdf-markdown` makes zero bytes of a scan with no text
layer. Converting `PLAY-2002` gave `<!-- page 1 -->`, as spec 008 says, so a
scan is still asked about, and its emptiness is still the finding. Running
exercise 02 with an empty note, for its new task 7, found the replay's step line
counting the failed note as an artifact: `5 artifact(s) from cache` beside
`4 artifact(s) reproduced`. That is fixed, and R6.30 row 3 now states both
lines (#584). Live, against a local MLflow and the stub model, the note's trace
was `ERROR`, holding `every input it reads is empty: documents`, with no model
span and `dossier.review: needed`. The incident beside it was asked once.

Two slips of process were caught on the way. An Edit refused in the same batch
as a commit shipped #581 without its spec status. A `grep` for `FAILED` exits 0
when it finds one, and let a failing check through. CI's architecture check
caught the first. Both are now in the working notes.

---

`/verify` read the day's sixteen rules against their tests, and found a defect
older than all of them. A step reading an `aggregate` step's output was handed
nothing, whatever its mode. The aggregate's one answer is filed under `*`, and
every reader looks an earlier step's answers up under a document's key or a
group's. So a `per_file` reader was never asked, and a `per_group` or
`aggregate` reader was asked about an empty input and cached under the hash of
nothing. It is R3.16's defect in another place. No rule said an aggregate could
be read, and nothing refused a pipeline that did. R3.19 refuses one at load
time. No committed pipeline or test reads an aggregate step, so refusing cost
nothing. R4.23's prose had claimed a step reading a skipped step is not asked,
for a reason that did not hold, and now cites R3.19 instead.

The same pass tightened four tests and one spec row (#577). R4.20's `--plan`
row was proved only through the function every reader calls, and is now proved
through the CLI as well. That test first passed a mutant half the time: a run
and a try started in the same second differ only in their random suffix, so
the suffixes are now pinned. A try's MLflow run gained the manifest a run's
has, the plan it resolved, without writing one to disk (R4.24 row 3, verified
live). Beside it, R4.26 refuses two of `--plan`, `--replay` and `--doc`
together. Before, each pair ran one command and silently dropped the other.

---

`dossier run --doc KEY` tries a prompt on one document (R4.18 – R4.25). The
live checks behind R6.25 ran exercise 10 four times, 9 calls each, when only
`PLAY-3005`'s 4 pages mattered, and aiming at one document took an in-memory
patch script. A run over some documents is a **try**. The design question was
that `dossier eval` must never score one as the pipeline's result.

- **What a try asks:** every step, only about the named documents; a
  `per_group` step about each one's whole group, so its question and key are a
  full run's (R4.18). A key no source holds stops the try before anything is
  asked (R4.19).
- **Where it goes:** `tries/<id>/`, named as a run's files are, and no manifest
  under `runs/` (R4.20, R4.22). `eval`, `--plan` and the moved-since warning all
  find the pipeline's result through the newest manifest there, so none can
  mistake a try for a run. Its answers are cached under a full run's keys, and
  the next full run is served them (R4.21). An `aggregate` step is skipped, and
  its line says why (R4.23).
- **MLflow:** recorded as a run is, tagged `dossier.try` with the documents, and
  it registers and links no pipeline version: a version lists only the full runs
  that produced it (R4.24).

The acceptance rule R4.25 runs the loop a person does: a full run, two tries
with the prompt edited between them, and eval still on the full run. While it
was red, it failed exactly where the spec said a try must not go: after R4.19
added `--doc`, eval took the try's manifest for the latest run and stopped on a
document the try never asked about. Live against a local MLflow with the stub
model, a try on `PLAY-3005` made 0 calls with its pages cached, and 4 calls
(4 LLM spans) after a prompt edit. Both were FINISHED and tagged, with no
version linked, while the full runs before them each link theirs. `runs/` was
untouched, and eval still scored the full run's 6 documents with no call.
Exercise 10 gained task 8.

---

An `enum` field is shown its values, and an answer outside them is named
(R6.25 – R6.27). The model had never been told `severity`'s vocabulary: the
generated schema limited field names only, and the prompt was meant to say the
rest. Live on 2026-09-29, `gpt-5.4-mini` answered `severity` with `latency`,
`ERROR` and a heap-usage sentence off exercise 10's panel pages. `INC-4830`
shows why it has to be told: every page prints `SEV-1`, and gold's `critical`
is a reviewer's reading of it.

- **The schema:** an enum field's record is now a variant of its own, holding
  one of its values or `null` (R6.25). A declaration with no enum generates the
  same bytes as before, so no key moves.
- **The finding:** a value outside the vocabulary is an `invalid` field finding,
  not a document failure, and it is re-derived on every read (R6.26). So
  `dossier eval` names it on runs cached before the rule. Its replay is handed
  the declaration's values, as the scorer is handed its kinds.
- **The acceptance rule:** R6.27 proves the two wired together through the CLI.
  It was added after `/discover` had written only the unit rules, because either
  could be MET while the slice was broken, as R3.16 once was.

R6.25's own live check changed the rule before its code. `gpt-5.4-mini`, which
reads a schema as guidance, answers only the fields the *first* variant names.
With the variants alone it left `severity` out of every page. With `severity`
first, it dropped the others. With a description only listing the fields, it
answered `severity` on three documents of six. The description that worked,
"Answer every one of these fields: …", got every field on every page and every
`severity` inside the vocabulary. Haiku 4.5, held to the schema, answered
either way. Ollama accepted the schema: `qwen3.5:4b` held `SEV-1` to
`critical`, but `qwen3:1.7b` repeated one record until it ran out of tokens,
where the old schema took seven seconds. Held to the vocabulary, a model
sometimes picks a value where it used to abstain: Haiku answered `major` on a
panel page. The value is valid and wrong, and it is scored so.

---

A `per_part` step's fields are scored once per document (R7.46 – R7.51), and a
field the run never answered is scored at all (R7.50). The list slice had noted
the first and left it. A step reading one page at a time answers a field once
per page, and `score_document` gave every record its own verdict:

- `INC-4830` prints `SEV-1` in the header of all three pages, so its `severity`
  counted three verdicts against a one-page picture's one.
- A page that said "not on this page" was a miss against gold's value. That is
  why exercise 10's prompt tells a page to leave a field out, not abstain.
- A judged field sent the judge only the last page's record, an abstention as
  often as not, and gave its verdict to every page. That was code disagreeing
  with R7.17, found while writing the rules, and fixed by R7.49 rather than
  patched on the side.

Now a field is one verdict per document. Pages that abstain are left out while
another page answers, and the field is correct only when every page that gave
a value is. A miss names its page, `page-002.png: '2026-07-30' does not match
'2026-07-28'`: a document's result carries the part each record came from, set
where the run and its replay know it. A judged field is judged once per
distinct answer and evidence, and one unsupported page fails it. Decided with
the maintainer over "any page right is enough", "the first page wins", and
refusing `output:` on a `per_part` step, which would have taken the vision
judge with it.

R7.50 applies in every mode. A declared field gold verifies and the run gave no
record for was unscored, so a run that left out what it was unsure of was never
wrong about it. It is now an abstention, named `not answered`. **`per_file`
scores can fall** for a pipeline whose model leaves fields out. No test in the
suite depended on it, and exercise 10's stub replies answer each field gold
verifies on exactly one page, so none of its figures move. Its task 7 overrides
`PLAY-3005`'s pages one at a time to show each case: a second date read off a
panel, an abstention, and silence on every page.

**The live check (2026-09-29)** ran exercise 10 on `openai:gpt-5.4-mini` and
on `anthropic:claude-haiku-4-5-20251001`, with the user's MLflow on. Both
models fell into the trap task 7 stages. Pages 2 to 4 of `PLAY-3005` answered
`incident_date` from their panels (`2026-09-02`, `2026-09-01`), and
`affected_systems` and `root_cause` from what each panel showed. Every such
miss named its page. The page-by-page judge asked one verdict per distinct
answer: nine on `gpt-5.4-mini`, eight on Haiku, whose page 2 abstained. The old
code asked six, judged `PLAY-3005` on page 4 alone, and would have scored its
`root_cause` 100%. `gpt-5.4-mini` never read `Resolved:` as the incident date
on four of six documents. R7.50 counts each as `not answered`, and it drops
`incident_date` to 33.3%, where before the field would have read 66.7% over
three documents. Haiku abstained honestly and read page 1's date. Its
`severity` is 100% only because R7.47 ignores the pages that said "not on this
page". The field was then renamed `resolution_date`, after the line the
documents print. Run live again, `gpt-5.4-mini` answered it on every document,
83.3%, and its one miss was page 2's peak date.

It also found two bugs the suite could not: the stub runs record nothing to
MLflow, and no stub refuses a schema.

- With MLflow on, every `per_part` run stopped after its first document,
  `Expecting value: line 1 column 1 (char 0)`. The trace's response parsed the
  joined `<part>` text as JSON. Each page's answer is now shown under its
  name, read back from the server as such (R15.6, #550).
- Anthropic answered every page, then refused every judge call with
  `400 Bad Request`. The judge's hand-written schema was open, and the generated
  stage schema always had been closed (R9.21, #549).

R9.20's one line said `400 Bad Request` and nothing more. Anthropic's reply
body says why, and would have named the cause in one sentence.

---

A field may be declared `kind: list` (R6.24, R7.40 – R7.45), which is what
`affected_systems` always was: `_fixtures.md` gave `INC-4821`'s gold answer as
`["payments-api", "ledger-batch"]` while the scoring example kept it as one
string, "because a field record's value is a scalar". A list is answered one
record per item, each with its own span, so every system is grounded on its own
evidence and the record and the schema the model is shown are unchanged: no key
moves. Only a list may be answered twice in one reply; any other field answered
twice is refused on the reply, where the one retry can put it right. A list is
one verdict per document, correct when the run's items and gold's are the same
set, case folded, order and repeats aside, and one ungrounded item fails it.
Gold writes it as an array; `"payments-api, ledger-batch"` is refused rather
than split, and so is `[]`, since a run cannot say "none" apart from "not
stated". Beside the percentage, the line prints item precision and recall --
`50.0%   items: precision 75.0% (3/4), recall 60.0% (3/5)` -- and MLflow records
them, and nothing gates on them. `score_document` now takes checks paired with
records rather than keyed by field: keyed by field they collapsed to one check
per field, which items with their own evidence could not survive. Noticed on
the way and not changed: a non-list field a `per_part` step answers on several
pages is still scored once per page.

---

`render: browser` is part of what a web source's fetch asks (R2.26, R1.40 rows
8 and 9). Added to a source already held from a sitemap, it had changed
nothing: no `<lastmod>` moved, so no page was fetched, and every page stayed held
as a shell. The crawled site that exercise 18 was being written against hid it,
because a crawled page has no marker and is fetched every sync anyway. Checked
live: `docs.astral.sh/uv/concepts/projects/`, held from its sitemap, drew all
10 pages at the next sync, and the sync after that fetched none.

---

A field may be declared `kind: boolean` or `kind: duration` (R7.36 – R7.39),
which is what the contract audit's `auto_renew` and `notice_period` needed
(`docs/second-use-case.md`, finding 2). A boolean is `true` or `false`, or
those two words quoted, and nothing else: `1` and `yes` are reported
unreadable, and `false` is an answer where `null` is the abstention. A duration
is a whole number of days, weeks, months or years, or ISO 8601 with one
component, and a bare `90` is refused as `07/08/2026` is. Lengths convert only
where the conversion is exact -- a week to seven days, a year to twelve months
-- so `3 months` against a gold `90 days` is incorrect, with a detail that says
a month is not a fixed number of days. The finding had assumed the two were one
answer; the maintainer decided they are not. There is no `number` kind, since
an `amount` with no currency is a count. A kind is not in the schema the model
is shown, so declaring one moves no key. Earlier the same day, `cli/main.py`
(2,485 lines) became one module per command plus a `bootstrap` holding the
builders tests replace, and `execute()`'s 30 keyword arguments became
`RunInputs` (what can change an output, R0.5), `RunRecording` (what may not,
R10.4) and nine arguments of its own.

---

A source whose listing fails no longer stops `dossier sync` (R2.27). Before,
the failure left the command as a traceback, and the sources after it were never
synced. The web connector's crawl, which fails a listing on purpose rather than
tombstoning what it did not reach (R1.38), made that an everyday case.

Now `sync_source` catches a failure raised while listing, as it already caught a
failed fetch (R1.9), and leaves the source as a listing that never finished
leaves it: nothing tombstoned, no mark moved, anything owed still owed. The
command names the source and the reason, syncs the rest, ends a tracked run
`FAILED`, and exits `1`.

- **Checked live.** `www.python.org/about/` with `crawl: 5`, before
  `quotes.toscrape.com/js/` with `render: browser`. The first was named with
  its reason, and the second still synced its 11 pages, drawn by Chromium
  through the installed entry point.

---

A `web` source that says `render: browser` holds each HTML page as a headless
Chromium draws it (R1.40 – R1.43), which resolves spec 001's open question 10.
`dossier` still asks for the page itself, and hands what the site sent to the
browser. Every request the page's scripts make comes back to the connector:

- requests to the site go through the same path as every page, so
  `robots.txt`, `delay:` and `429` hold, and a script is asked once a sync;
- requests to other hosts are the browser's own;
- images, fonts, media, other frames and anything but `GET` are refused.

A script that navigates away is answered `204`, because an aborted navigation
replaced the drawn page with Chromium's error page. R1.43 supersedes R1.2: a
drawn page is not the site's bytes. It is held in UTF-8 behind a byte-order
mark, because Chromium read a test page by its header's charset over its
`<meta>`, and a page held in either could be read back in the other.

Playwright is the extra `browser`: three packages, where crawl4ai, built on it,
was 86 more for the same API. A missing Chromium is named, never downloaded. A
`FakeBrowser` draws in the unit suite, and three `live` files have a real
Chromium draw the same pages offline.

- **Checked live.** `quotes.toscrape.com/js/`, crawled: 11 pages either way,
  and the notes held no quote until drawn (19 s against 7). A second sync
  stored nothing. `docs.astral.sh/uv` drawn took 217 s against 12 to 20, and its
  theme rewrote every in-page link as absolute.

---

A `web` source with no sitemap is crawled when it says `crawl:` (R1.37 –
R1.39), which resolves spec 001's open question 7. `www.python.org` asked for
this: it publishes no sitemap, and its listing failed on the `404`. The crawl
starts at `url`, follows the `<a href>`s under it, and asks each URL once, by
way of the path every request already takes, so `robots.txt`, redirects,
`429` and `delay:` hold as they did. `fetch` hands back the bytes the crawl got.

A crawled listing is complete, so a crawl that cannot tell it reached
everything lists nothing, rather than letting sync tombstone what it missed.
That covers a `5xx`, a `429`, no answer, a redirect loop, `url` not being a page
or being disallowed, and one URL more than `crawl:` allows. `crawl:` has no
default.

crawl4ai's `BFSDeepCrawlStrategy` was read and declined, because it gets
exactly that wrong:

- it reads links only from pages that succeeded, and ends normally without the
  rest;
- it fetches each level concurrently and caps in the order pages finish;
- it sends its requests outside the path R1.33 – R1.36 govern.

- **Checked live.** `www.python.org/community/` with `crawl: 300` and
  `delay: 0.5`: 69 pages in 70 seconds, past 14 broken links and 51 redirects
  that add a missing slash; a second sync wrote nothing. `/about/` with
  `crawl: 5` failed naming `…/about/legal/`. `/psf/` failed on its first
  request, because it redirects to `/psf-landing/`, outside the source.
  `docs.astral.sh/uv`, crawled, listed the same 84 keys its sitemap names.

---

`html-markdown` 1.3.0 writes a page that declares one `<main>` as that
element, without the `<nav>` inside it (R8.33). This resolves spec 001's open
question 6: every page of a website carried the site's header, menus, sidebars
and footer into its note, and on both sites the live check read, they made up
about half of it. The page's own declaration was chosen over a CSS selector per
source. Converter options are part of `K_convert`, but no manifest pins them
and no replay composes them, so a selector would have needed specs 004 and 005
as well. crawl4ai's `PruningContentFilter` was read and declined. It is a
density heuristic, and importing it would put a browser and HTTP clients right
of the hash boundary. A page with no `<main>`, or two, is written whole. That
includes every exported file in the playground, so their artifacts kept their
hashes.

- **Checked live.** `docs.astral.sh/uv/getting-started/installation/` went from
  12,446 characters to 6,480, and `www.djangoproject.com/foundation/` from
  17,815 to 7,800. The article text is whole in both.

---

A `web` source stops at a `429` and keeps a pace (R1.35, R1.36), which
resolves spec 001's open question 9. The live check of R1.29 – R1.34 found the
site it waited for: `djangoproject.com` answered `429` to 70 of the 91 pages
under `/foundation/` within seven seconds, with no `Retry-After`, and the
connector asked all 70 after the first refusal. Stopping alone would not have
been enough. A page with no `<lastmod>` is fetched every sync in key order, so
the same first pages spent the site's allowance every time and the rest could
never be held. Now the first `429` ends the sync's requests to the site, and
the pages left are owed (R2.23). Requests start at least the longer of the
source's new `delay:` and the site's `Crawl-delay` apart. crawl4ai's
`RateLimiter` and Scrapy's AutoThrottle were read from source and declined:
neither stops at a `429`, neither applies `Crawl-delay`, and each comes with
its framework.

- **Checked live.** Without `delay:`, the connector sent one request that was
  answered `429` and left the other 85 unsent. With `delay: 1`, one sync held
  all 91 pages in 92 seconds. `docs.astral.sh/uv`, with neither setting, is
  unchanged: 84 pages, and a second sync fetches none.

---

The open questions answered on 2026-09-27 landed together: Confluence comments
(spec 001 Q2, R1.23 to R1.25, R8.30), text a page includes (Q3, R1.26, R1.27),
Jira's custom fields (spec 008 Q4, R1.28, R2.26, R8.31) and HTML's declared
charset (Q6, R8.32). Each was read against a real server before it was written.

- **Jira, Q4's twin.** A Jira Software Data Center 10.3 ran in Docker. A file
  added, replaced or removed, and a comment added or edited, each moved `INC-3`'s
  `updated`, and a windowed JQL search found it every time, so nothing changed.
  Jira was OOM-killed at a 2.5 GB cap and ran out of Metaspace with it capped at
  512 MB. It ran at 3.3 GB.
- **Comments.** On the local Confluence, a comment and a reply left their page at
  version 1 and out of a windowed search, and `type = comment` found both, naming
  the page as container. Only `child/comment?depth=all` returns a reply;
  `children.comment` gives 25 top-level comments at most.
  - So `comments: true` holds the page and each answer byte for byte,
    `{"page":…,"comments":[…]}`.
  - The page's marker gains `+c` over its comments.
  - A windowed listing also asks `type in (attachment, comment)`.
  - A real `dossier sync` fetched only `360453` after a third comment, and its
    note listed the thread with `· reply to`.
  - The same server's PDF export of that page held no comment, so the export's
    marker leaves comments out.
- **Included text.** Editing `Escalation contacts` left the page including it at
  version 1, while its `export_view` changed. CQL finds including pages with
  `macro in (include, "excerpt-include")`, and the storage format says which page
  each names.
  - On cwiki, KNOX's `Release Process` links to `News` and includes `Footer`. The
    listing took three requests and marked it by `Footer` alone: a plain link is
    not an include.
- **Custom fields.** Asked with `expand=names,schema`, Jira says what each field is
  called and holds. On Jira Software, `Development` (`any`) is a 3 KB Java object
  string and `Rank` is `0|i0000f:`, so `any` and `Sprint` are left out.
  - A real sync and convert of Apache's `HADOOP-18254` wrote `Hadoop Flags:
    Reviewed` and `Target Version/s: 3.4.0`, and none of its five `any` fields.
  - R2.26 puts what a fetch asks in the source's configuration hash, so every held
    issue is fetched again once and gains them.
- **Charsets.** A page is read in the charset it declares, and a label is read as
  a browser reads it. `iso-8859-1` is windows-1252 to a browser, and `0x96` is `–`
  there and a control character to Latin-1.

The local servers' timebomb licences expired the same evening: every request
answered 401, and a restart did not help. So the last live reads were done
against the public servers, read-only.

---

A `web` source reads a website from its sitemap (R1.29 – R1.34), with
documentation sites as the case it was written against. One connector for
every site: `url` is a prefix, the sitemap is the listing, a page is keyed by
its URL relative to the prefix and marked by its `<lastmod>`, and
`html-markdown` converts it. The listing is complete, so a page
gone from the sitemap is tombstoned, and for the same reason a sitemap or a
`robots.txt` that cannot be read fails the listing instead of emptying it.
Scrapy, crawl4ai, trafilatura and ultimate-sitemap-parser were considered and
declined (spec 001 records why); `protego` reads `robots.txt`, because the
standard library's parser misreads wildcards. Run against real sites on
2026-09-27: `docs.astral.sh/uv` listed 84 pages, each with a `<lastmod>`, and a
second sync fetched none; `www.python.org` publishes no sitemap, so its listing
failed on the `404` as R1.29 row 6 says (question 7); `djangoproject.com`,
checked as well, answered `429` to 70 of the 91 pages under `/foundation/`
within seconds (question 9); about half of a median note, on both sites that
listed, is navigation (question 6); and Cloudflare's email obfuscation
re-encodes 13 of uv's pages on every fetch and leaves `[email protected]` in
the note where `ruff@0.3.0` was. Page chrome, sites
without a sitemap, credentials and throttling are open questions 6 – 10.

`eval --compare` refuses two runs whose calls were shown different reference
documents, by key or by snapshot (R7.35). R7.8 already refused different
audited documents, for the reason that applies here too: a field can move with
what the call read, and the delta would credit the configuration with it. By
snapshot, because a procedure tightened in place keeps its key. What a call was
*shown* is the test, so a pipeline that declares `reference:` and never reads it
still compares. To compare two configurations fairly after a procedure changed,
run the earlier one again; what did not read the procedure comes from cache.

`dossier run`'s warning that the source has moved now names a moved reference
document too, marked `(reference)` (R4.9 row 5). A tightened procedure used to
go unmentioned until two runs were compared, although `--plan` already named it
(R4.17). Exercise 17 showed the gap in its closing section, which is now gone;
its task 3 prints the warning, and a deleted procedure prints `gone
(reference)`.

`--plan` says `documents changed` for a step reading `documents@page_images`
when its document moves, and a converter now moves only the steps that read its
kind (R4.12 rows 11 to 13).

- **Before.** The plan asked whether a step read `documents` by spelling alone.
  A re-synced PDF printed `cached` for the step reading its pages, and the next
  run then asked the model about each new page. `converters changed` was
  decided for the whole plan, so fixing only the spelling would have flagged
  the page step whenever `pdf-markdown` moved, which renders none of its pages.
- **Checked live on exercise 10.** PLAY-3001 was replaced by a new one-page
  PDF. The plan named `PLAY-3001-checkout-latency-apm.pdf changed`, and the run
  made one call, for its one new page, with 8 from cache.
- **What the plan still cannot know.** A `per_part` key holds only a page's
  content hash (R3.12). A document replaced by bytes whose pages are already
  cached, such as one PDF copied over another, is served from cache even
  though the plan says `documents changed`. That is the same over-report R4.12
  already accepts for text that converts identically.
- **Found on the way, fixed in its own PR.** `pdf-images` went from 1.0.0 to
  1.2.0 in #453 and #456, and every page's bytes changed with it. Exercise 10's
  stub replies still named the old page hashes, so the exercise got a 422 from
  the stub on its first run. The replies now name the pages as `digests()` in
  `playground/toolkit/make_observability_docs.py` renders them, and a re-run
  matched all 9 calls, with the same fields, eval, calibration and replay as
  the transcript. The playground was the only thing that noticed: a converter
  version that moves every page moves every stub rule keyed on a page.

A windowed Confluence listing now finds a page whose only change is a file
(spec 001, R1.22), answering Q4. It needed a Confluence this project could write
to, and both servers read before were public. So a Data Center 9.2.21 ran in
Docker on this machine. A page created at 10:07 was given a file, and the same
file was uploaded again at 11:17. The page stayed at version 1 with
`lastmodified` 10:07, a `type = page` search from 11:15 returned nothing, and
`type = attachment` returned the file at version 2, naming the page as its
container only when `expand=container` asked. So under a window the page was
never listed, its files were never asked for, and R1.18 row 2 held only on a
complete listing. A removed file did not move the page either, and search
cannot see it at all, so a removal still waits for the next complete listing
(R2.22). The listing now asks a second question, which files changed in the
window, and a third, which of their pages the source's query matches, 50 ids at
a time. The query is never applied to the files: `label = runbook` matches pages
and not what they carry. A real `dossier sync` against that server then read
`3 known · 1 changed · 0 new -> 1 fetched` after a third upload, fetching only
`360453/audit-note.txt`. What it costs on a public server was measured too:
about five files a day change on cwiki and a few on confluence.atlassian.com, so
a quiet sync there is two or three requests, not one. Confluence's first
upload also hung the 8 GB WSL VM this machine shares with three other stacks,
until its container was capped with `mem_limit`.

---

A `per_group` or `aggregate` step reading a `per_group` step's answers is now
handed them (R3.16 rows 1 and 2). Until now it was handed nothing.

- **Found live, not by the suite.** Exercise 16 was re-run after its keys moved
  to `PLAY-`. In that pass the accepted `per_group` `verify` step recorded its
  `extract` input with the hash `e3b0c442…`, which is the SHA-256 of nothing.
  - A group step files its answer under the group, `extract/ACME-2024.json`.
  - A call reading a set looked earlier answers up under its members' keys
    only, so `{{extract}}` rendered empty in every such call, and the run
    reported success.
  - R3.16's rows say what each call holds, but the rule was proved only at
    load time, where a reader is admitted or refused. The exercise's own
    transcript showed the input's path and not its hash.
- **The fix.** A call reading a set looks answers up under its members and
  their groups (`filed_under`). A `per_file` step's answers are under the
  members, and a `per_group` step's under the group. Nothing outside the set can
  match, since a group is named by its first segment. Run and replay share the
  one function that renders a value, so a replay recomposes the same keys.
- **What moves.** The key of every call that read a group step's output, which
  was composed over an empty value. Such a call is asked again. A run made
  before the fix recorded keys that nothing composes now, so a replay of it
  stops by name (R4.14). The answers it would reproduce were made without the
  evidence the step declared.

`reference:` works as spec 003 always said it did: context, not audited (R3.17,
R3.18, R4.16, R4.17, R5.15 and R7.34). A field now cites only what its own call
was shown (R6.23). Both gaps were found while landing `per_group`, and neither
was caused by it.

- **What `reference:` did before.** The run put the reference sources in with
  the audited ones. A `per_file` step was asked about each procedure as though
  it were an incident, and filed an answer for it. `{{reference}}` was filled
  from the same per-document map as `{{documents}}`, so it held the incident a
  second time and never a procedure. No test had ever run a step that read
  `reference`: the example pipeline in spec 003 declared one, and nothing
  executed it.
- **What it does now.** Reference documents are never audited.
  `{{reference}}` holds every one of them, under its key, in every call of
  every mode. A pipeline reading it with none declared is refused at load
  time.
- **Manifest, plan and judge.** The manifest pins reference documents under
  their own list, so a replay shows each call the procedure as it was. A plan
  re-runs only the steps that read `reference` when one moves. A procedure that
  has gone is a move, since every one of those calls was shown it. A judge is
  shown the procedures beside the document, and a described judge is calibrated
  on that same prompt.
- **Citations.** A `per_file` or `per_part` call's check was handed the whole
  corpus. An answer about one incident that quoted another, with the quote
  really there, was graded grounded. R6.3 row 2 had been proved only at the
  domain layer, where `check_source` is right when handed the right documents.
  `_citable` now decides what a call was shown, once, for the run and the
  replay alike.
- **Live.** Playground exercise 17 ran every rule against the stub. It found
  one thing no rule covers. `dossier run`'s "the source has moved since run"
  warning (R4.9 row 4) compares the audited documents only, so it says nothing
  when a procedure moves. Its SOLUTION.md records it. It was left for a rule
  of its own.
- **Noticed, not changed.** `--plan` tests raw input names against the source
  keywords. So a step reading `documents@page_images` never reports
  `documents changed` or `converters changed`, though its keys move (R4.12).

---

What came back and what was left out now reach MLflow (spec 011, R11.24 to
R11.26). R2.25 added `returned` to a sync's line, and R8.27 added `left out` to
a convert's, but neither reached the record. A sync that revived `audit-note.pdf`
named it in the terminal and attached a `changes.json` holding two empty lists.
It recorded `/fetched` 3 against `/known` 2, `/changed` 0 and `/new` 0: the
unbalanced line R2.25 had just fixed on screen, still unbalanced in MLflow.
`changes.json` now carries `returned` beside `changed` and `tombstoned`, with
`from` and `to` only when the item came back with other bytes, as its line does.
A sync records `/returned`, and a convert records `/left_out`, both at zero too,
because a missing count reads as one never measured (R11.4 row 3). Which counts
are recorded stays one decision in `dossier.domain.tracking`, so the change was
two names in a tuple and the counts that fill them.

---

A step can ask one question of several files: `per_group`, the fourth mode (spec
003, R3.15 and R3.16, with R4.15, R5.14, R6.22, R7.32 and R7.33). It resolves
`docs/second-use-case.md` finding 1, which had been open since before spec 004
was built.

- **Why.** A supplier contract is a master agreement and its amendments. The
  cap is in the master and the renewal date in amendment 3, so `per_file` asks
  each file a question none of them can answer. `aggregate` asks every contract
  at once, which cannot be cached or scored per contract.
- **Where a group comes from.** The key, up to the first `/`. A `group_by`
  pattern and a committed membership file were weighed and not adopted. Every
  connector already keys a file under what it belongs to, and a replay can
  recompose groups from the keys its manifest pins, with nothing new recorded.
  The cost is that contracts named by a filename convention in one flat folder
  must be sorted into subfolders first.
- **What follows from it.** Each group's call holds its members as an
  `aggregate` call does (R3.13). Its key holds their inputs and no other
  document's (R5.14). A field cites a member (R6.22). Gold is written per group
  (R7.32), and a judged field is shown every member (R7.33). A `per_file` step
  reading a group's answer is refused at load time (R3.16).
- **Found live, not by the suite.** A group of one, `GLOBEX-2023`, asks exactly
  what `per_file` asks of `GLOBEX-2023/master.md`. So the two had one key, and
  switching a step to `per_group` served the `per_file` answer, whose
  `document` was the member's key, filed as `GLOBEX-2023.json`. Cached bytes are
  served verbatim (R5.5), so the fix could not be to correct the name on the way
  out. The group's name went into the key as an input, R5.14 row 5, the way R5.10
  row 5 had put the document's. Playground exercise 16 found it on its first
  pass.
- **The stub model** now logs, for every call, the keys of the documents its
  prompt wrapped. That is how exercise 16 tells one call per file from one per
  contract.

Two gaps turned up that `per_group` did not cause and did not fix. A step's
`reference` input is filled from the same per-document map as `documents`. And
a `per_file` step that cites another document in the corpus is graded VALID,
because the run hands `check_field` every document, not the one the call read.
R6.3 row 2 is proved only at the domain layer. Both are for a discovery of their
own.

---

`dossier sync` now counts an item that comes back after it was tombstoned (spec
002, R2.25).

- **Why.** `known` counts the rows that were active before the sync, and `new`
  the keys the ledger has never held. A file put back in its folder is neither,
  so it was fetched and counted nowhere. The sync printed
  `2 known · 0 changed · 0 new -> 3 fetched`: three fetched, and two accounted
  for. Playground exercise 04 found it.
- **The count.** `returned` is printed beside the other counts, only when there
  is one. Each returned item is named under its source line, with both addresses
  if its bytes changed while it was gone. It is counted as returned, not as
  changed, because `changed` counts items that were known.
- **A bug fixed on the way.** An item goes back to `active` in any sync, as R2.7
  row 3 always said. Only a complete listing did that before, so an item that
  came back unchanged in a windowed listing stayed tombstoned.
- **R2.20's counter-example** now says the item is not named *as tombstoned*.
  It is named as returned.
- **Checked live.** Exercise 15's export, put back, was re-run against
  confluence.atlassian.com: `2 known · 0 changed · 0 new · 1 returned -> 0
  fetched`.

---

A converted PDF is now the same bytes on every machine (spec 008, R8.28 and
R8.29). That resolves open question 2, which had been answered with a finding: R8.1
did not hold between Windows and Linux. `INC-4830`'s postmortem does not embed its
fonts, and two things differed:

- **The fonts.** PDFium drew Helvetica with Windows' Arial on one machine and with
  its own built-in fonts on a Linux image that has none. docling-parse, Docling's
  default renderer, matched fonts against the machine's font folders, and fell
  back to a Windows font by name. On Linux the half-photocopy lost a heading, and
  `pdf-images` gave two artifacts.
- **The compression.** Pillow's PNG encoder compressed with zlib-ng on Windows and
  zlib on Linux. CPython's own zlib on Windows is zlib-ng too.

What changed:

- **Fonts (R8.28).** `FPDF_SetSystemFontInfo(None)` takes the machine's fonts
  away from PDFium, once per process. `docling-markdown` reads through Docling's
  pypdfium2 backend, since docling-parse has no setting to stop borrowing.
- **Compression (R8.29).** `_png` writes every PNG part itself, compressed by
  libdeflate (`deflate==0.9.0`, a new pinned dependency in the `pdf` extra).

The versions went up: `pdf-images` 1.2.0, `jpeg-pages` 1.1.0 and
`docling-markdown` 1.1.0, so their artifacts convert again once.

Measured before anything was written, on Windows 11 and in `python:3.12-slim` at
the lock's versions, every artifact is byte-identical on both. The half-photocopy
keeps its heading. The default suite pins the hashes that need no models, and CI
holds them on Linux. The `live` suite pins Docling's.

---

A model that fails now stops every command that asks one in the same line (R9.20).
`dossier run` always printed `incident-audit: POST <url> failed: ... (after 3
attempts)` and exited 2. `calibrate` and `eval`, with and without `--compare`,
ask the judge, and let the same failure out as a Python traceback. A live
calibration during R11.23 printed one. The three failures `run` caught are now
named once, as `MODEL_FAILURES` in `cli/main.py`: an unset endpoint, a provider
nobody installed, and a request refused or never answered after R9.17's retries.
Anything else keeps its traceback, because a bug turned into a line would read as
something the user could fix.

Writing it showed that R11.23 was wrong about `eval`. The rule said an eval opens
its MLflow run once its work is done. In fact it opens the run before it asks the
judge, so the judge's traces sit inside it (R7.18 row 5), and a judge nobody could
reach left the run `RUNNING`. R11.23 now names three commands, and the eval's run
is closed `FAILED` by the same `failed_if_stopped` the other two use (rows 7–9).
Checked live against MLflow 3.15.1 with the stub stopped: `calibrate` and `eval`
each printed the one line with exit 2, and both runs ended `FAILED`. Exercise 07
gained a task 8 that walks through it.

---

Spec 008's open question 2 has an answer, and it is not the one the spike
expected. `docling-markdown` converted the same three PDFs on Windows 11 and in
`python:3.12-slim` on Linux (x86_64). Every package was at the lock's version,
and the inputs were byte-identical on both sides:

- **The photocopy and `PLAY-2002` came out identical.** A page that is a picture
  renders to the same pixels everywhere. The layout model, TableFormer and
  RapidOCR read those pixels the same way on both machines.
- **The half-photocopy did not.** On Linux, page 1, the one read from its text
  layer, lost a heading, and two of its tables merged their header row into
  their first row. Pages 2 and 3 matched.

The text layer was the same on both machines, but the page image Docling's
models look at was not. The postmortem embeds none of its fonts, so PDFium draws
Helvetica with Windows' fonts on one machine and with its own fallbacks on the
other, and about a tenth of each page's pixels differ. That is R8.1 row 3's
"font file outside its input", read by PDFium on the converter's behalf.

- `pdf-images` renders the same way, and its bytes differ even on the photocopy,
  where the pixels match: Pillow's Windows wheel compresses PNGs with zlib-ng,
  and its Linux wheel with zlib.
- `tests/scans.py` builds a different photocopy on each machine for the same
  reason, which is why the Linux side converted the Windows-built bytes.

A replay still reads the cached artifact (R4.7). What R8.1 should say about a
machine's fonts is left for a spec change.

---

Conversion has an automatic case, and who chose a document's kind now decides
what happens when nothing can read it (spec 008, R8.24 – R8.27). A source that
declares no `convert:` leaves both choices to `dossier`: the kind from the
default table (R8.10), and the converter from what is installed (R8.13).

- **R8.5 is superseded.** It stopped the whole run over any unclaimed pair, so
  one `.jsonl` attached to `KAFKA-20416` stopped Apache's source.
- **Nobody declared the kind (R8.25).** The document fails on its own, with R8.6's
  shape: it is named with the pair, the rest converts, and the exit is 1.
- **The source declared the kind (R8.24).** It is configuration, and it still
  stops the run with exit 2. A tie between two installed converters is now
  refused once, as a tie, instead of as every document "having no converter".
- **Kinds per media type (R8.26).** `convert:` may be a map, such as
  `{application/pdf: [markdown, page_images]}`, so a Confluence space can ask for
  pictures of its PDF exports without asking them of each page's JSON.
- **A type left out on purpose (R8.27).** A media type mapped to `[]` is held and
  read by nothing, and counted as `left out`. This is the way out of R8.25's cost,
  a source exiting non-zero on every run over a file nobody wants read.
- **Leaving out is never a default.** A new kind of attachment still fails the
  first time it arrives.

Two things the playground found while the transcripts were re-run:

- **The stop was not total across sources.** Each command converted source by
  source, so when the second source was refused, the first had already written
  its artifacts. `refuse_unconvertible` now resolves every source before any
  converts.
- **A source choosing its own converter (open question 3) was not built.** A
  manifest pins one converter per pair, and a replay finds a document's
  converter by its pair (R4.7). So two sources answering one pair differently is
  a change to spec 004's manifest, and there is no corpus asking for it yet.

---

The half of a sample a judge exists for now has a bar of its own (spec 007,
R7.30 and R7.31). The figures of R7.26 – R7.29 were meant to be seen before
anyone decided what to gate on, and once they had been seen, the decision was
narrow:

- keep the agreement bar;
- let a gold set add, per grounding state and beside it, the share of
  unsupported cases its judge must catch
  (`described: {agreement: 0.90, unsupported: 0.875}`).

0.875 is R7.11's eight unsupported cases with one let through, written as a
share so a larger sample is held to the same rate. Eight is the floor below
which the share is not a measurement. The bar is optional, so every existing
`judge.yaml` loads and gates as it did.

Run through the CLI on exercise 10's workspace, the described judge at 90%
against its 0.90 bar had caught 6 of 8 unsupported cases. It is reported
without the bar and withheld with it:
`unsupported 6 of 8 (75.0%) is below the agreed 87.5%`.

The same work closed the gap the R7.29 live check found (spec 011, R11.23). A
calibration stopped by an unreachable model had left its MLflow run RUNNING, and
empty, forever. `failed_if_stopped` now closes a stopped run FAILED for both
commands that open theirs before their work: `dossier run`, whose own block it
replaced, and `dossier calibrate`. A server that fails to close is swallowed, so
it never replaces the error that stopped the command (R10.6).

The spec's first draft had a sync and a convert end FAILED too. Reading the code
before building showed that both open their run only once their work is done, so
the rows were corrected before a line was written. Live against MLflow 3.15.1
with the model unreachable, the calibrate run is now FAILED.

---

What playground exercise 15 found, fixed (R2.23, R2.24, R6.21, R8.20 row 7,
R1.18 row 6). Writing an exercise against a real Confluence turned up two
things the suite had called MET. Sync asks for a page's files only when the
listing returns the page. So a refused export was reported once, and then the
next windowed sync had nothing to fail on and moved the watermark past it.
Adding or removing `export:` did nothing until `--full`. R1.19 row 6 and R1.20
row 3 were green because their fake Confluence ignored the CQL window. Both went
back to NOT MET. Two rules followed. A key whose fetch failed is recorded in the
ledger's `owed` table, and its item is visited at every sync until the key is
stored, its item stops carrying it, or a complete listing drops the item (R2.23).
A change to any key of the source's own is recorded as a hash, and the next
listing is complete without refetching unchanged items (R2.24). That also means
a narrowed Jira query tombstones what it no longer matches, rather than waiting
for `--full`. Both fakes now honour the window, and with either mechanism
switched off, the test that depends on it fails. Checked on cwiki: with
`export: pdf` added, the 403 comes back at every sync, and the watermark holds
until it is fixed. The second finding was worse: a text step was asked about
every picture with an empty document. Every picture then had the key of `""`,
and the second one was served the first's answer, naming the first. R6.13's
reasoning described exactly this and its rule did not cover it. R6.21 does, and
replay makes the same decision. R8.19's acceptance test had pinned the bug, by
asserting two model calls where the second was that empty call. The shared HTML
reader now keeps a non-breaking space at the edge of bold, which markdownify
dropped, so both HTML converters are at 1.1.0. A page's files are listed once
per sync, where each file fetched had listed them again.

---

A judge's calibration now says what its agreement figure hides (spec 007,
R7.26 – R7.29, from analysis.md §4.8). The gate had been comparing one number,
`agreement >= threshold` over twenty cases, and three things were invisible
behind it:

- 20 of 20 supports a 95% lower bound of only 83.9%, the figure R7.11's own
  threshold note had to argue from by hand;
- a judge that calls everything supported scores 60% on R7.11's sample and
  has a kappa of 0;
- a judge can hide a weak unsupported half behind a strong supported one,
  though catching unsupported claims is its whole job (R7.12).

The Wilson lower bound, Cohen's kappa and the two halves as "agreed of cases"
are now worked out in `domain/judges.py` with `math` and `statistics`. That
was a recorded choice over statsmodels and scikit-learn: `domain/` imports
only the standard library and pydantic. The figures go wherever the agreement
already went: a second terminal line in plain words, the calibration file,
and the calibrate run's metrics and description, rounded as printed. A figure
that cannot be measured is said in words and sent as no metric, because
MLflow has no null and a 0 would be charted as a judge that scored 0.

The figures are reported only. What the gate compares is a threshold, and it
waits for a person who has seen them. Each rule went NOT MET → MET in one PR.
Live against MLflow 3.15.1, the terminal, the file, the six metrics and the
description agreed.

The same live run found something no rule covers. A calibrate stopped by an
unreachable model left its MLflow run RUNNING, empty, forever. `dossier run`
closes a stopped run as FAILED, but only in code; no spec states the rule for
any command.

---

An HTML page or a CSV file someone exported no longer stops its source (spec
008 R8.21 – R8.23). Synced from Apache's Jira, `KAFKA-20416` carries a CSV, a
JSON-lines dump and two files Jira labels `text/html`. Nothing claimed either
pair, so R8.5 stopped every document in the source, the issue included.
`html-markdown` reads an HTML file with the reader `confluence-page-markdown`
uses, now shared as `converters/_html.py`. Refactoring onto it left both live
cwiki notes byte-identical, so that converter's version stayed. It takes out
the `<head>` as well as `<style>`, `<script>` and `<template>`. Otherwise
markdownify writes the `<title>` as a line of its own above the heading that
repeats it. An image is its alt text and file name (R8.22). The red row showed
markdownify writing a `data:` URI's whole base64 into the note. The converter
decodes UTF-8 itself: handed bytes, BeautifulSoup guesses the encoding with
`charset-normalizer`, which MLflow installs, so output would have depended on a
machine's extras. `text-csv` writes a CSV as its own text. A markdown table was
rejected because it rewrites every row a model then quotes. A page's breadcrumb
stays in its note. Telling navigation from content by class name is the
heuristic `trafilatura` was rejected for, and R8.21's first row, which said the
note opens with the heading, was corrected rather than bent.

Checked live on `KAFKA-20416`: the 40 MB CSV and both "HTML" files convert.
One of those files is a JSON log dump and the other a plain-text topology,
uploaded without extensions, so reading them as HTML costs the topology its
indentation, which grounding's whitespace fold absorbs. The source is still
stopped by its three `.jsonl` files, reported as `application/octet-stream`.
Whether an attachment nothing claims should stop its whole source at all is
spec 008's open question 7, a change to R8.5 left for a decision.

---

A Confluence space can be audited (spec 001 R1.15 – R1.21, spec 008 R8.19 –
R8.20). Spec 001 had said a page would be exported as a PDF, because its images
carry meaning the storage format loses. A real server disagreed: the export is a
user-interface action, not a REST route, and `cwiki.apache.org` and
`confluence.ecmwf.int` refuse it (`403`) while serving the page's JSON. So a
page is held as Confluence renders it for export
(`expand=body.export_view,version,space`), labelled
`application/vnd.dossier.confluence-page+json`. It is keyed by its id, never its
title, with the marker `v37`. Its files are `<page id>/<file>`, marked by
attachment id *and* version, because each alone misses a case. The PDF became
an addition rather than the whole: `export: pdf` also holds `<page id>.pdf`,
whose marker digests the page's files' markers too, since an image replaced in
place changes the PDF but not the page. A refused export fails that document by
name and holds the watermark back (R1.20). A PDF missing without a word would
read exactly like a page with none, and R1.12 had already ruled out probing
around a refusal. `confluence-page-markdown` writes the note with `markdownify`
and BeautifulSoup, both pinned: no escapes, and no table of contents, which
repeats the headings and carries its render time in a class name, so no two
fetches of a page are the same bytes. Images are written by file name. Jira's
header decision moved to `connectors/atlassian.py`, so both connectors
authenticate one way. `atlassian-python-api` was rejected: it is built on
`requests`, and its hundreds of write methods would end R1.1's "the write is
absent".

The fakes found one real bug before any server did. httpx *replaces* a URL's
query with `params`, so `params={}` stripped `?version=2` from a file's download
link, which would have fetched the latest version rather than the one the
marker named. The live checks found the rest of the facts the spec now records:
`confluence.atlassian.com` exports only with `X-Atlassian-Token: no-check`, and
serves the redirected file only to the session cookie that asked. Two exports
of one version differ in the trailer's random `/ID`. Synced from cwiki, two KIP
pages came with 66 images, and both notes came out clean. What is left is
spec 001's open questions (Cloud, comments, included pages) and spec 008's
question 5: `convert:` is per source, so `page_images` of an export would be
asked of its page too.

---

Reviewers review in MLflow. The people who can say whether an answer is right
rarely run `dossier`, so the daily run's record became the place they review it
(spec 015). Every trace now opens with the document it read and closes with the
answer, which MLflow shows as the trace list's Request and Response (R15.1), and
a run tags what it doubts -- a failed document, a field ungrounded or invalid --
so the review queue is a filter in a URL (R15.2). A spike against MLflow 3.15.1
came first and changed the design twice: labeling sessions, MLflow's assigned
queues, are Databricks-only, so the queue is a filter; and the open-source trace
view records every verdict's author as the fixed string `User`, whoever is
logged in -- found in the JavaScript it ships -- so a reviewer's expected value
becomes gold under the name of the maintainer who applies it, the recorded
author and the trace kept in its reason. `dossier review pull` reads the
verdicts back through a port of its own, `ReviewSource` -- valid `HUMAN`
assessments only, so an override replaces what it overrode and the judge's
verdicts stay the judge's -- and writes `feedback.jsonl` and a report by step and
field (R15.3) and `candidates.jsonl` (R15.4); `dossier review apply
--verified-by` checks every candidate before writing anything and passes the rest
through `apply_correction` (R7.7), the half of spec 007's review design that had
no caller. It is the one read from MLflow, fenced as the dataset, version and
prompt reads were: an architecture test holds that no run, plan, replay, eval or
calibration can name a verdict (R15.5). Built while another session held the
repository's one open outer loop, so each rule went from NOT MET to MET in one
PR. Live, end to end: verdicts posted as the UI posts them, pulled, applied under
`a.aleks`, and a following run served entirely from cache.

A span is compared after folding what a reader cannot tell apart. `locate_span`
normalised whitespace only, so an honest citation failed on a difference nobody
can see, and was scored incorrect before its value was looked at (R7.4). Two
converters had just made that likelier: OCR text brings ligatures and line-end
hyphens, and the Jira note writes `**Status:** Done`. `grounding.fold` is now the
one fold both `locate_span` and `page_of_span` search through, applied to both
sides: NFKC (R6.17); typographic quotes, apostrophes and dashes as their plain
forms, before NFKC as well as after, because NFKC writes `″` as two primes
(R6.18); a hyphen ending a line between letters read both ways -- joined for
`certifi-`/`cate`, kept for `well-`/`known` -- with the page taken from the
reading the span was found in (R6.19); and links, inline code, strong, emphasis
and strikethrough as their words, emphasis read by CommonMark's flanking rules so
`lb_acq_01` and `3*2` stay text (R6.20). No fold reaches a letter, a digit or
case. Grounding is re-derived from a cached answer on every read, so no key
moved; verdicts, and scores, can.

Checked against playground exercise 11's seed, which posts the corpus notes'
markdown as Jira descriptions: read as wiki markup, `**Severity:** major` becomes
`***Severity:*** major`, and three spans per issue had failed to ground. All 19
ground now.

A Jira issue converts. The connector held every issue as `application/json`,
nothing claimed that pair, and `dossier convert` refused the whole source: a Jira
source could be synced and never audited, which playground exercise 11 walked
into. Claiming `application/json` would claim every JSON document any source
holds, so the connector now labels an issue with what wrote it,
`application/vnd.dossier.jira-issue+json` (R1.14), and `jira-issue-markdown`
claims that pair. The note is decided in `domain` by `jira_issue.note`: the key
and summary as a heading, six fields when the issue has them, attachments by
name, the description, then the comments in Jira's order under author and time
-- and nothing else in the payload, so a custom field or an avatar URL is never
something a model can quote (R8.16). A thread Jira sent only part of says how
much is missing (R8.18). The description and comments are Jira wiki markup,
written as markdown by `jira2markdown` 0.5.1, a new core dependency pinned
exactly, with its escaping off and `\r\n` made `\n` (R8.17). Pandoc's jira
reader and rendered HTML through `markdownify` were considered and are recorded
in spec 008. The test fixture is an issue in the shape a real Jira Server sends,
recorded from `issues.apache.org/jira`.

A live sync of Apache's public Jira converted two real issues cleanly -- a stack
trace in `{noformat}`, a comment in Korean -- and a third found the next wall: an
issue carrying `.csv`, `.jsonl` and `.html` attachments refuses the whole source,
because nothing converts those types (R8.5). The HTML one is what the Confluence
converter will claim.

A photocopy converts to text. `pdf-markdown` reads a PDF's text layer, and a
scanned contract has none: it converted to three page anchors and nothing else,
and no field in it could ever be grounded. `docling-markdown` runs Docling over
the document, one page at a time -- a page with a text layer read from it, a page
whose layer holds no printable character OCR'd whole (R8.14), the decision made
in `domain` by `ocr_pages`. It claims `pdf-markdown`'s pair and is opt-in, so a
workspace chooses it with `converters: [docling-markdown]` in `sources.yaml`, and
`answering` decides once, before selection, who answers each pair (R8.13): the
manifest still pins one converter per pair and a replay needed no change. A
misspelt name stops the command; it used to be a key nothing read.

Its models are part of it. Docling pins its layout model to `main` and downloads
it on first use; the converter hands Docling a model folder instead, checks every
weight file against the SHA-256 of a pinned commit before a page is read, and
fails the document naming the `hf download` line that fixes it (R8.15). Proved
live with every socket refused. The photocopies are made by `tests/scans.py` from
`INC-4830`'s published PDF rather than committed, so what OCR read can be compared
with the text it was photographed from: the root cause comes back word for word,
at about twelve seconds a page, and byte-identical from a second process.

What a spike found before the rules were written, and a fresh install found
after: RapidOCR's direction classifier turned one upright line into noise (`H ed
ngu e n ng r y e nr c eng`), so it is off; Docling's automatic OCR dropped the
spaces between words that whole-page OCR kept; and RapidOCR's ONNX models ship
in its wheel while the dictionary its torch engine wants does not -- the first
spike had quietly downloaded it, and a clean venv failed on the missing file. The
converter names the ONNX models by path, and a fresh install converts offline.
Docling brings torch, so CI installs every extra but `docling` and the tests
that run it are `live`; and `docling-core` caps typer below 0.27, which holds the
whole install at 0.26.

R5.3 is superseded by R5.13. "Changing the model identifier changes every stage
key" stopped being true the moment a step could keep its own model while the
pipeline's moved; what survives is that a key holds the model its step is asked
with, and moving it moves that step's key alone. R5.3's test is reclaimed
rather than deleted -- each of its rows is still true of a pipeline whose steps
name no model -- with the per-step rows beside them, every key composed from
`ResolvedPlan.model_of`. Seen live: a pipeline moved from `extract` on Ollama
to no step model re-asked `extract` with the pipeline's Gemini, and `verify`,
whose input came out byte-identical, stayed in the cache.

A pipeline version knows each step's model. `version_params` is the one
function the run's record, the eval's and the version's are built from, so
`model/<step>` beside `prompt/<step>`, for a step asked with its own model,
reaches all three and the version hash taken over them: two pipelines that
differ only in `extract`'s model are two rows in the Models tab (R11.22,
R13.1). A step asked with the pipeline's records nothing, and the test pins, as
a literal computed before the change, the version hash of a pipeline naming
none -- a new one would have registered every existing pipeline as a new
version with nothing changed.

A step is asked with its own model. A pipeline named one model for every step,
and the common real shape -- a cheap model to extract, a strong one to verify or
report -- took two pipelines (analysis.md 4.3). `model:` on a step overrides the
pipeline's for that step alone, held at load time to what the pipeline's is held
to, `steps.<i>.model` named in the error as the loader names every step key
(R3.14). The pipeline's `model:` stays required: it is the default, and the judge.
The manifest records a step's own model only where it differs, and never as
`null` -- a `model_serializer` leaves the field out -- so every pipeline written
before resolves to the same bytes, and naming the pipeline's own model is naming
none. `ResolvedPlan.model_of` is the one answer to which model a step is asked
with, and the run, `--plan` and `--replay` all ask it, so the three cannot
disagree about a key; `--plan` compares it per step, so the pipeline's model
moving leaves a step with its own cached. `execute` takes a client per model a
step names and refuses one with none before anything is written, and the CLI
builds each lazily, so a step served from cache needs no endpoint for its model.
Live, with the real clients against two local servers: `extract`'s Ollama
digest checked once and asked three times, `verify` asked three times through
the Gemini route, each artifact's record naming its own model, and a second run,
a replay and a `--plan` asking neither.

Traces stay apart at concurrency. MLflow keeps traces opened on different
threads apart -- four opened at once through `MlflowClient`, against a real
3.15.1 store, came back holding a span each with durations MLflow measured --
and `dossier`'s tracker did not: it held one current trace for the process, so
at `--concurrency 3` every span was started under the trace opened last, and
the first trace to end cleared the id the others were still writing to. The
`Tracker` port now promises that a trace is current in the thread that opened
it, a promise and not a signature (R11.21). The fake keeps it, or it could not
fail when the real one broke it; `BestEffortTracker` holds each thread's place
and lost flag, taking the place and opening the trace under one lock so it is
the place `MlflowTracker` names a trace the server lacks by (R10.24); and
`MlflowTracker` holds each thread's trace, root span and pending verdicts.
Nothing is buffered or replayed -- that was the first design, and it needed
timestamps handed to the port for MLflow to show a duration it measures by
itself when traces are live. The run records `concurrency` as a param and
nowhere else. Live, `--concurrency 3` against a real server: three traces,
each holding its own document's LLM span, 1.35-1.41 s each as MLflow timed
them, and no record lost.

A run asks about several documents at once. A step over four hundred documents
was four hundred round trips end to end, against a hosted provider that would
have answered ten together; R9.17's backoff is what made offering more safe,
because the `429` it provokes is waited out. `--concurrency N`, else
`DOSSIER_CONCURRENCY`, else 1 -- per machine like an endpoint, and never in
`pipeline.yaml`, whose hash is the pipeline's (R9.19). One at a time stays the
default because a local model often answers one request at a time, and four
queued at it outlast the timeout and are sent again. A step's documents go to a
pool and come back in document order, so the step lines and `runs/` are what
one at a time writes; documents start in order, so once one fails none after
it starts and the error is the one a loop would have stopped at. Steps stay in
order, and a `per_part` document's pages stay one after another: a (step,
document) is the unit of a key and of a trace. What a run did once it still
does once -- the client built at the first miss, the Ollama digest and the vLLM
repository checked before the first call -- behind a lock each, because three
workers missing together are one first miss.

A run says what it spent. Every provider reports on every answer what it cost
in tokens -- `usage.prompt_tokens`, Anthropic's `input_tokens`, Ollama's
`prompt_eval_count` -- and every client threw it away with the rest of the
body, so the first question asked of "a new audit in an afternoon" had no
answer. A reply now carries the counts: `Reply` is a `str`, so every reader of
an answer and all sixty-odd fakes that return plain text stay as they were, and
a count the provider did not give is `None`, never 0 (R9.18). The provenance
record holds what producing its artifact cost, summed over its attempts --
R6.2's refused attempt cost as much as the one that stood -- beside `attempts`
and outside the key on the same terms (R5.11). And each step's line ends with
what its calls cost in this run: `extract: 3 document(s) · 0 from cache · 0
failed · 3,612 tokens in · 636 out`, nothing at all on a re-run served from
cache, and `tokens not reported` rather than a zero nobody measured (R5.12).
The line is `step_line`'s, so the MLflow description says it too (R11.17).
Tokens, not money: a price per model is the user's to declare, and tokens are
what any price multiplies. MLflow reads it too: the run gains `tokens_in` and
`tokens_out` beside `model_calls`, and each LLM span carries MLflow's own
`mlflow.chat.tokenUsage` rather than a `dossier.` attribute, because MLflow 3
adds every span's into the trace's `mlflow.trace.tokenUsage` and shows it in
the trace list -- verified against a live 3.15.1 server, three traces reading
1204/212/1416 each and the run 3612/636 (R11.20). A count is not content, so it
is recorded under `capture=hashes` as well.

A rate limit is not an answer about the document. One `429` from Gemini behind
OpenWebUI -- the project's default endpoint -- raised straight out of the model
client and stopped `dossier run` with exit 2 at the document it hit, which over
four hundred documents is a question of when. A request answered `408`, `409`,
`429` or any `5xx`, or not answered at all, is now sent again unchanged, at most
twice, waiting what the server's `Retry-After` asks when that is at most a
minute and otherwise 0.5 s then 1 s, jittered down by up to a quarter (R9.17).
The numbers are both official SDKs', not chosen here. It all happens inside one
`complete`, so the stage sees one answer, R5.5 counts one call and R11.2 shows
one span; a `401` or `400` still fails on the first answer, and a failure after
three says so: `answered 503 Service Unavailable (after 3 attempts)`. The decisions
are `dossier.domain.retries`; the one loop that acts on them is `_http.request`,
which every client already sent through, and each client takes a `sleep` so no
test waits.

MLflow can sit behind authentication. `DOSSIER_MLFLOW_AUTH` names the mode --
`none`, `basic`, `bearer` or `oidc` -- chosen, never inferred from which
variables are set, and `DOSSIER_MLFLOW_USER` (Created by) is never a login
(R10.16). One MLflow request auth provider, registered by entry point, puts the
credential on every request: runs, traces from the async exporter, the
registries and dossier's own startup check, so the header checked is the header
sent; MLflow's own `MLFLOW_TRACKING_TOKEN` in a shell decides nothing (R10.17).
The startup check makes one read that needs the credential, because MLflow's
basic auth leaves `/health` open, and a 401, 403 or redirect to a login page
stops the command before any work (R10.18). An `oidc` client-credentials token
is fetched before any work and again once no more than
`DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS` (30) remain -- verified against Keycloak
with 60-second tokens and a 93-second run, 0 records refused (R10.19). A private
CA is `DOSSIER_MLFLOW_CA_BUNDLE`, trusted on all three connections (R10.20).
Every command says how many records it lost (R10.21), and the first 401 or 403
is said as it happens -- a warning, never a refusal (R10.22). The only secret
never touches the environment; what is written there is MLflow's own provider
name and cert path. After pulling, reinstall (`uv sync`) so MLflow finds the
entry point; a stale install is refused by name.

A trace counts as recorded once the server is seen to hold it. No trace call
reaches MLflow's server -- its exporter sends a trace after it ends, on a thread
of its own -- so a trace refused there raised nowhere and R10.6 counted none.
As a record closes the exporter is flushed and the run's traces are looked up
by run without their spans, one request per hundred; each one missing is
counted once, as a trace and as a record. The adapter names them by place, not
id, so nothing read back reaches a run. Verified live through a proxy refusing
two of four trace uploads: `2 trace(s)`, and two held on the server (R10.24).

MLflow printed `🏃 View run` to stdout *before* sending the update that closes
a run; on a Windows pipe (cp1252) that raised, and every run stayed `RUNNING`
behind exit 0. The tracker now tells MLflow to print nothing (R10.23).

Spec 013 is *pipeline versions*; prompt publishing is **014**. Two sessions
wrote a spec 013 in parallel and the logged-models one merged first, so the
prompt rules renumbered from R13.x to R14.x before they ever reached `main`.
Ids never move once merged -- these had not.

A record says what it is. `eval of 20260921T153441Z-07f1` was filterable and not
readable, and four `calibration of incidents` in a list were one measurement
each and told apart by nothing. A name is now rendered from a template per
command kind, exactly as an experiment is -- `{prefix}` and `{label}` carrying
their own separators so an unconfigured name is byte-identical to the one
recorded before (R10.10), and a placeholder a command cannot fill refused before
any work. The version a person means by `v2` is supplied rather than counted: a
count of the runs on a server would name the same eval differently on another
machine, and differently again after a record was lost (R10.11).

R10.3 is superseded by R10.12, which names the four `mlflow.*` tags dossier
writes. Its counter-example said `mlflow.user` and `mlflow.source.name` were
"left as MLflow sets them"; `MlflowClient.create_run` reads `mlflow.user` out of
the tags handed to it and defaults it to `unknown`, and sets no source at all --
so they were left *empty*, and Created by, Source and Description were blank on
every record dossier had ever written. `mlflow.runName` stays out: MLflow reads
a name from that tag as well as from `create_run`, and R10.10 gives a name one
source.

An eval says what produced what it scored. The pipeline hash, each step's prompt
and schema hashes, the converters and the judge's rubric, read off the manifest
it already reproduces and never recomputed -- a converter pinned at `1.3.0` is
recorded as `1.3.0` on a machine where `1.4.0` is installed (R11.11). It
describes itself from the figures it printed (R11.12), attaches the per-document
lines the terminal loses (R11.14), and a comparison names the steps that differ
between its two runs, from the decision `--plan` already makes (R11.13) -- the
cause of a delta on the same page as the delta.

The judge is readable. Its span carries what a stage's carries under the same
capture setting, instead of the model identifier alone (R11.15), and its verdict
is an MLflow assessment on the trace an eval already opens -- a projection, never
`mlflow.genai.evaluate` reaching a verdict of its own (R11.16). That one was
green in the suite and broken live: MLflow exports traces asynchronously, so
`log_feedback(trace_id=...)` right after the span answers
`RESOURCE_DOES_NOT_EXIST` -- the asynchrony R10.9 was written about, in a second
place. `FakeTracker` records the call and returns and `BestEffortTracker`
swallows the exception, so in production the assessment would have been missing
with no error anywhere. Verdicts are now held and sent in `end_trace`, after the
exporter is flushed.

Every record describes itself now, not only the two that score. `run`, `sync`,
`convert` and `calibrate` opened a record whose Description -- the first thing on
its page -- was empty, so eight `sync incident-audit` records in a list were eight
identical rows. Each hands the lines it printed to `tracker.describe`, under a
header naming the kind (R11.17). Verbatim, indentation stripped: `sync` and
`convert` keep the lines they echo and pass the same list on, and the two lines
`run` and `calibrate` share with a terminal they have not printed to yet -- their
record closes inside the application layer -- moved into `domain/tracking.py`,
where both readers call them. One format string, two consumers, so a figure
cannot move in the terminal and stay put in the record. A run that failed on a
document is described all the same, failure count included; a run that stopped
at its first cache miss on an unreachable model closes FAILED and describes
nothing, because nothing was counted.

A run says what produced it, as its eval already did. R11.11 gave the eval the
prompt, schema, converter and generated-schema versions read off the manifest;
the run that *wrote* that manifest recorded three params, so "which prompt moved
between these two runs" was answerable about the evals and not about the runs it
is actually asked of. `version_params` now runs over the plan as it is resolved,
and the two records agree because they are one function over one set of data
(R11.18). And `dossier_version` is on every record rather than on the eval alone
(R11.19) -- the value R4.9 already puts in every manifest, which no sync, convert
or calibration could previously be tied to at all.

One thing was considered and left out, and the other was split in half. MLflow's
**prompt registry** was refused whole because loading from it would make a
server-held version something dossier reads back, which is the hazard R12.4
fences off. Spec 014 takes the half that writes and leaves the half that reads:
the objection was never to publishing. Logged models, named there as the thing
worth doing next, is spec 013.

A pipeline version is a thing in MLflow. The Models column beside every record
was empty, and MLflow's logged model is the object built for the one comparison a
change gate exists to make: this version scores 80%, the next scores 90%. What
fills that slot is not the LLM -- `dossier`'s **model** is the LLM -- but the
pipeline at a version, so spec 013 says *pipeline version*, records the pin as a
param of it, and spec 000's vocabulary carries the term.

Its identity is a **version hash** over everything that produced the answers, and
emphatically not `pipeline_hash`: that is `text_hash(pipeline.yaml)` and does not
move when a prompt does, so keyed on it an edited prompt shared a row with the
prompt it replaced and there was nothing to compare. The spec was written with
that mistake in it and R13.1 row 3 caught it. The document count is deliberately
outside the digest -- a run over five documents instead of four is the same
version measured more widely (R13.1).

A run links the version on its **outputs** and an eval on its **inputs**, because
a run made it and an eval only measured it (R13.2); the accuracy `finish_eval`
already computes goes to the version as well as the run, from one dict, so the two
cannot disagree and a withheld field is missing from both (R13.3, R7.17). A third
port was needed for `DatasetRegistry`'s reason -- registering **returns** an id --
and it matters more here, because this one is called during `dossier run`, the
command R10.4 is about; the id reaches a tag, a link and the terminal and nothing
on disk (R13.4). A registry that cannot be reached costs the Models tab and never
the run, at construction as well as at every call, and says so (R13.5).

Four facts came from a live spike run *before* the spec was written, and three of
them changed it: MLflow creates a new logged model every time it is asked by name,
so a version has to be found rather than assumed; only `name AND params` returns
one, where either half alone returns many; `log_outputs` fills a run's own model
column while the registry's `source_run_id` does not; and metrics against a model
accumulate across runs with each value carrying the run it came from.

A prompt is published, never loaded. MLflow's prompt registry exists to be read
from, and `dossier` takes only the half that writes: `dossier prompts publish
<pipeline>` sends one prompt per step, named `incident-audit.verify`, and one per
judged field's rubric, named `incident-audit.judge.root_cause` -- the field's
name rather than a step's, because two steps declaring one field declaration
publish it once (R14.1, R14.2). The dot is forced: MLflow's
`_validate_model_name` refuses `/` and `:`. Each version carries
`dossier.prompt_hash` in all 64 characters, which is the same value that enters
the stage key and the only thing tying a version in the UI back to the run that
rendered it (R14.3). `register_prompt` versions unconditionally, so a publish
asks `latest` first and sends nothing when the hash already matches -- verified
live, twice, against a real server rather than only against the fake (R14.4).
Nothing reads a prompt back: there is no `load` on the port, no `load_prompt`
anywhere under `src/`, and a test asserts both (R14.5). A run links the version
carrying the hash it rendered, found by tag rather than by recency, so a prompt
edited since cannot attach its newest words to a run that never saw them
(R14.7) -- best-effort, because a registry that is down must cost the link and
never the run. A judge's record links the rubric it judged with the same way:
`dossier eval` for every field it did not withhold, cached verdicts included,
and `dossier calibrate` once per field it measured (R14.9). The linked version
is the rubric a person wrote, not the judge's whole prompt -- R7.19 hashes the
wrapper too, and only the rubric is published. A prefix MLflow would reject is refused
with the rest of the tracking settings, before any work, by every command that
records (R14.10) -- `eval` and `calibrate` met it as a traceback with their run
open, and `run` after its record had opened. The prefix itself became a namespace:
`DOSSIER_MLFLOW_NAMESPACE` goes in front of every name dossier publishes into
MLflow's global namespace -- a prompt's and a gold set's dataset's -- because two
workspaces each holding `gold/incidents` merged their records into one dataset,
R14.8's failure in a worse form (R10.13). It supersedes R14.8's prompt-only
prefix and R14.10's refusal (R10.14), and the retired
`DOSSIER_MLFLOW_PROMPT_PREFIX` is refused by name rather than ignored, since
ignored it would stop namespacing a machine without a word (R10.15). A dataset
name would take `/` -- checked live -- but one namespace goes in front of every
published name, and prompt names decide. A comparison links the rubric both its sides
were judged with, once, because both are judged with the checkout's (R14.11);
R14.9's row 8, which said a comparison links nothing, was replaced in place by a
counter-example that is still true, as R11.7's row 5 was. And a pipeline version links the
prompt version each of its steps rendered, so the Models tab says what a version
is made of (R14.12): `dossier run` links them, because it built the version,
from the lookups R14.7 already makes -- one answer, linked to the run and to the
version. MLflow keeps a model's linked prompts as one set (checked live), so a
later run of the same version changes nothing, or adds a prompt published since. A prompt name is global and carries its pipeline, which is
unique within one workspace and no further -- found live, when a publish from one
checkout arrived as `v2` of another's prompt -- so a per-machine prefix went in
front of every prompt name (R14.8), since widened to the namespace below
(R10.13). A prompt fetched at run
time would be an input to a key no checkout can reproduce, a route into a run no
review passed through, and a network read on the replay path.

A comparison is a record. `dossier eval --compare a b` printed per-field deltas
and recorded nothing, on the reasoning that it reads two runs each already
recorded when they ran -- true of the two scores, and not of the **delta**, which
is a figure neither run holds and the only one the change gate exists to produce.
It is now one MLflow run of `a/<field>`, `b/<field>` and `delta/<field>` in an
experiment of its own kind, because a delta is not an accuracy (R11.8); the fields
that got worse are named on it, present and empty when none did (R11.9); and it
links the gold set's dataset as an eval does (R11.10). R11.7's row 5 moved with it:
the boundary that still holds is a replay, which opens no run at all.

A gold set is a thing in MLflow. `dossier dataset publish <pipeline> --gold
gold/incidents` sends it as the evaluation dataset named after it -- one record per
verified document, `inputs` the document key alone because MLflow merges a record
onto the hash of its `inputs`, `expectations` the verified answers with an
abstention carried as `null`, and the snapshot address a record tag (R12.1, R12.2).
One gold set is one dataset however many pipelines measure themselves against it
(R12.6), and `dossier eval` logs it as an input of its own run, naming a dataset
that has fallen behind the answers it just scored rather than obeying or refusing
it (R11.7). Publishing a gold set that has not moved sends nothing at all, because
MLflow's digest is `sha256("<name>:<last_update_time>")` and a redundant merge
would offer a person two identical versions to compare (R12.3) -- which a live
publish found while the suite was green, the fake having computed that digest from
the records. The dataset is a projection, one way only: no score, key or file is
ever computed from one, and the id a server hands back may reach a tag and the
terminal line and nothing on disk (R12.4). Publishing is the one command that
refuses when tracking is off, since its whole output is the record, and a
file-backed MLflow server is refused by naming `--backend-store-uri` rather than by
an MLflow traceback (R12.5). It needed a second port: publishing **returns** a
dataset id, which `Tracker`'s contract forbids and R0.10 leans on, so
`DatasetRegistry` sits beside it.

A picture is judged. A field whose span is in no text because the stage read
pictures is `described` -- a third grounding state, neither a pass nor a failure:
the evidence is on a page the model looked at, and a string search is the wrong
instrument for it (R6.15). `dossier eval` puts such a field to the judge with the
document's pages in place of a transcript, and the pages enter the verdict's key
where the text hash does, so a described verdict and a grounded one about the
same candidate are two entries (R7.21). `judge.yaml` declares a bar per state --
`root_cause: {grounded: 0.95, described: 0.90}`, a scalar still meaning the
grounded one (R7.20) -- `dossier calibrate` measures each state against its own
sample and records it beside the other (R7.22), and a field is reported only when
every state it can produce is calibrated and above its own bar (R7.23). The
vision judge agreed with `a.aleks` on 21 of 22 visual cases, twice, with no case
flipping; the bar is **0.90**, below the text judge's because reading a page and
then judging it is the harder job -- the case it misses reads a hypothesis
table's `Verdict` column as an assertion (R7.24). Before this, eval raised
`KeyError` on a document with no text layer.

An image converts. `png-pages` and `jpeg-pages` claim the pair R8.10 resolved an
image to and nothing produced, so a screenshot could be synced, held and hashed
and never converted (R8.12); every part of a `page_images` container is a PNG,
because the composition root labels each one `image/png` as it unpacks. And
`dossier[pdf]` declares Pillow, without which the shipped `pdf-images` raised
ImportError on its first page -- invisible because mlflow's matplotlib supplies
it to every development environment and to no other.

A per_part run replays. Each part is in the recomposed stage key, as the run put
it there; leaving it out built a key no such run had ever written, so every
per_part run was irreproducible and `dossier eval` -- which scores a replay --
could score none of them (R4.14).

A picture is evidence now. `dossier[pdf]` ships `pdf-markdown`, which reads a
PDF's text layer and introduces each page with its anchor, and `pdf-images`,
which renders every page to a PNG -- one artifact, a deterministic container of
parts, because forty keys for a forty-page document would let a version bump
invalidate its pages one at a time (R8.11). An input names the kind it reads,
`documents@page_images`, and bare `documents` still means `markdown` so no
pipeline written before it changed (R3.11); a kind no source was told to make
stops the run from the configuration alone, before a byte is fetched (R4.13).
A `per_part` step is shown one page at a time, keyed and cached and retried per
page (R3.12), and writes each answer under its document (R0.13). A stage may
hand a model image parts, and each provider sends them in its own form -- a data
URI, a base64 source block, an array beside the message (R9.16). Before this the
only media type a stage could read was text, `page_images` was an artifact no
step could name, and a chart was unreadable by construction.

A page number is derived, not asserted. `source.page` has been in the field
record since the shape was written and nothing ever checked it: the model said a
number and no code disagreed. It is now read off the anchor the located span
sits after, and `null` for a document with no pages -- because a fabricated `1`
is the same lie in a smaller font (R6.14).

The default kind is a table. An image resolves to `page_images` rather than to
`markdown`, so the pair a person is told to claim is not the one an image cannot
honestly supply (R8.10). `text/plain` converts instead of stopping the run.

A run leaves something to open. `dossier run` writes each artifact a step
produced or served to `runs/<run_id>/<step>/<document>.json` -- the key with
`.json` appended, `.md` for a step with no `output`, `aggregate.md` for an
aggregate step -- as each document completes, byte-identical to the cache entry
and with its provenance record beside it; a failed document leaves nothing, and
nothing under `runs/` is ever read back (R0.11). `dossier run --replay` writes
what it reproduced to `runs/<run_id>/replays/<replay_id>/`, never touching what
the run wrote, and writes nothing at all if any one artifact cannot be
reproduced (R0.12). Before this a run directory held only `manifest.json`,
every artifact lived solely in `.dossier/cache/stage/` under its key, and a
replay printed a count and showed nothing -- which playground exercise 01 found.

A Jira credential lives where every other per-machine value does. `token_env`
is resolved through the environment `.env` fills, so `DOSSIER_JIRA_TOKEN=…` in
`.env` reaches the connector, and a variable without the `DOSSIER_` prefix
written only there is refused by name (R1.8 rows 5-6). The header follows the
keys: a token alone is sent as Bearer, a `user_env` beside it turns the pair
into HTTP Basic, and a 401 is reported once rather than retried in the other
form (R1.12). `deployment: cloud` sends a listing to `/rest/api/2/search/jql`,
paged by token; absent means Data Center, paged by offset (R1.13). Before this
the composition root read `os.environ` alone while the miss message promised
`.env`, and Jira Cloud could be neither authenticated to nor listed.

A deletion is observable too. A connector declares whether every listing it
returns is complete -- the folder does, Jira does not, and one that says nothing
is refused where it is built (R1.11) -- and sync subtracts held from listed
against any listing that is complete for either reason, not only one it asked
for with no window (R2.21). `dossier sync --full` asks every source for an
unwindowed listing on demand, so what a source that narrows has dropped can be
tombstoned without a `fields` change to force it (R2.22). Before this a file
deleted from a folder stayed `active` for ever, which playground exercise 01
found.

A hash change is observable. `dossier sync` names each item it repointed under
its source line, with the snapshot address it held and the one it holds now,
both in full (R2.18), and each item it tombstoned (R2.20); the ledger keeps
every address a row has ever held in an append-only `revisions` table, seeded
from `items` for a ledger that predates it (R2.19); and the sync's MLflow run
carries the same two lists as `changes.json` (R11.6). Before this, the previous
snapshot of an edited document was recoverable only by elimination against the
store.

The judge is asked. `dossier eval` scores a free-text field by putting the run's
answer to the judge with the one question it was calibrated on -- is this
candidate supported by the document -- and prints how many verdicts were
judged (R7.17); a verdict is an artifact in the `judge` cache namespace, so
the judge is asked only on a miss and a comparison over the same candidate
asks nothing (R7.18); and the wrapper dossier puts a rubric in is hashed into
the calibration, so an edit to it is stale like a changed rubric (R7.19).
`/quality` found the gate below guarding a number nothing produced; these
three are what it guards now.

The judge is gated end to end, which is what `/verify` set out after when it
found `is_stale` with no caller anywhere in `src/`. A judged field's agreement
threshold is declared with the gold set, and a judged field with no threshold is
refused at load time rather than reported as though it had cleared one (R7.13).
The human-scored cases it is measured against live beside it, holding a
*candidate* answer and a verdict on it -- what a gold file cannot express, and
why the two are separate artifacts (R7.16). `dossier calibrate` measures a judge
against that sample and writes what it measured, never touching the bar it is
judged against (R7.14). And `dossier eval` withholds a field whose calibration is
missing, short or stale, saying which of the three it is, because they want three
different fixes (R7.15, R7.5, R7.6).

The report and the MLflow record make that decision **once**, in the command, and
the record is handed the answer. They were briefly allowed to work it out
separately, and disagreed about a judge that had never been measured -- a metric
recorded for a field the report had already refused to print, with every check
green. Spec 011 is the rule that forbids it: MLflow is a second place to read a
figure, never a second way of arriving at one.

The judge is calibrated. `openai:gpt-5.4-mini`, reached through a local
OpenWebUI, agreed with `a.aleks` on 20 of 20 human-scored `root_cause` cases,
twice, with no case flipping between runs -- and it marks the planted claim in
`INC-4830` unsupported, which is what tells a working judge from one that agrees
with everything (R7.11, R7.12). The threshold is **0.95**, agreed by `a.aleks`
on 2026-09-16: below what was measured, because 20 of 20 at N=20 supports a lower
bound near 84% rather than 100%, and above the 60% a judge calling everything
supported would score on this sample.

`dossier` reads a real remote source now. The Jira connector ships, issues and
the files they carry are separate addresses, and every request it makes is a
`GET` -- which is what finally made R1.1 provable rather than merely true
(R1.1, R1.4, R1.6). A held document is the raw payload its ledger row addresses,
not the projection its hash was taken over (R2.17); a changed `fields` list
re-evaluates the whole source it describes (R2.3); an attachment replaced under
an untouched issue is detected, snapshotted and tombstoned on its own (R2.6); a
step does not run for a document an earlier step produced nothing for (R6.13); a
converter declaring no version is refused where it is registered (R8.2); and a
credential is *named* in `sources.yaml` and never written there, resolved by
`dossier.config` and handed to the connector (R1.8, R9.8).

Spec 009's five providers are registered with their default endpoints: `openai`,
`gemini` and `hf` reach a model through one OpenAI-compatible client over httpx
(R9.12), `ollama` through its native API (R9.13), and `anthropic` through the
Messages API (R9.15). OpenWebUI is an endpoint, never a
provider (R9.7), and a `.env` file fills what the shell leaves unset (R9.11).
The project's default model is `gemini:gemini-3.5-flash-lite` through a local
OpenWebUI (`.env.example`). A vLLM serving another repository, or an Ollama tag
re-pulled to another digest, stops the run before its first call (R9.6, R9.4).
