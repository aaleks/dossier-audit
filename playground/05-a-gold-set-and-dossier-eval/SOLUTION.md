# 05 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

Terminal 1:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
    --replies playground/05-a-gold-set-and-dossier-eval/resources/replies.json \
    --port 8099 --log /tmp/dossier-calls.jsonl
```

Terminal 2:

```bash
mkdir -p playground/work/05/inbox/incidents playground/work/05/gold/incidents
cp -r playground/05-a-gold-set-and-dossier-eval/solution/workspace/. playground/work/05/
cp playground/corpus/incidents/PLAY-100[1-4].md playground/work/05/inbox/incidents/
cp playground/05-a-gold-set-and-dossier-eval/resources/verified-answers/*.json \
   playground/work/05/gold/incidents/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/05/.env

cd playground/work/05
D=../../../.venv/bin/dossier
$D sync incident-audit && $D run incident-audit
$D eval incident-audit --gold gold/incidents
```

That copy of the gold files is you accepting them. `solution/workspace/` has an
empty `gold/incidents/` on purpose — an agent is blocked from writing anything
under a `gold/` path in this repository, and the block is the point (R7.7).

---

## Task 1 — the gold set

```json
{
  "document": "PLAY-1002.md",
  "verified_by": "a.aleks",
  "verified_at": "2026-09-17",
  "fields": {
    "loss_amount":      {"value": null, "reason": "the note states that no financial loss was recorded for this incident"},
    "resolution_date":  {"value": "2026-03-19"},
    "severity":         {"value": "minor"},
    "affected_systems": {"value": "reporting-export"}
  }
}
```

**`null` versus absent.** `"value": null` is a person saying *the document does
not state this*, and it is a scorable answer: a run that abstains is correct, a
run that supplies a value is incorrect (R7.3). A field left out of the file is a
person who has not looked, and it is not scored at all. Collapsing the two would
invent a verdict nobody verified — task 5 shows the difference in the report.

The `reason` is not decoration either. A bare `null` is indistinguishable from a
field somebody forgot to fill in, and this file is read by a human a year from
now.

**Which name is matched.** The `document` field inside the file, not the
filename. The key is what a run reports a document under, and a file renamed on
disk is still the same verified answer (`load_gold` in
`src/dossier/application/eval.py`).

**What a gold file cannot hold, and why it matters:** nothing about a run. No run
id, no confidence, no model. Only a reviewer's decision enters the gold set, and
the strongest form of that guarantee is having nowhere to put anything else.

## Task 2 — the first score

```console
$ dossier eval incident-audit --gold gold/incidents
4 documents · 4 fields · overall 100.0%
  loss_amount        100.0%
  resolution_date    100.0%
  severity           100.0%
  affected_systems   100.0%
```

100% because the stub answers exactly what the gold says, which is what you want
from a baseline: from here, anything that moves is something *you* changed.

Note the shape. The overall figure opens the report and never closes it: every
field's own line follows, so it can never be all that is printed (R7.2).

```console
$ dossier eval incident-audit --gold gold/incidents     # with no run yet
incident-audit: no run to score. Run `dossier run incident-audit` first.
exit 2
```

Scoring reproduces a run from its own manifest and cache entries — exactly as a
replay does — so it asks no model and it needs a run to exist (R7.10).

```console
$ dossier eval incident-audit --gold gold/incidents     # two gold files broken
incident-audit: PLAY-1001.json: loss_amount holds [18400.0], and a gold value is a number, a string, true or false, a list of strings, or null
incident-audit: PLAY-1003.json: not JSON (line 11, column 1)
exit 2
```

Every file that does not read is named before anything is scored, so one pass
finds them all (R7.56). The line and column of a file that is not JSON depend
on where your edit left it.

## Task 3 — one prompt edit, four changed answers, two moved scores

```console
$ dossier run incident-audit --plan
incident-audit  4 document(s) · model openai:gpt-5.4-mini
compared against 20260917T210015Z-e8d2
! extract: prompt changed
1 of 1 step(s) would run · nothing written
```

`prompt changed`, not `cached` — the prompt template is in the stage key, so this
is a different question and the cache cannot answer it (R4.12, R5.2).

```console
$ dossier run incident-audit
run 20260917T210016Z-3069 · …
  extract: 4 document(s) · 0 from cache · 0 failed

$ dossier eval incident-audit --gold gold/incidents
4 documents · 4 fields · overall 87.5%
  loss_amount         75.0%   <- weakest
  resolution_date     75.0%   <- weakest
  severity           100.0%
  affected_systems   100.0%
```

Row by row:

| document | field | answer | verdict | why |
|---|---|---|---|---|
| PLAY-1001 | loss_amount | `"CHF 18'400"` (string) | **correct** | the amount scorer strips an unambiguous thousands separator and a three-letter currency written before or after the value. `currency` is still compared as its own field — the reply sets `"currency": "CHF"`, and without it this row would have failed on the currency, not on the number |
| PLAY-1001 | severity | `"MAJOR"` | **correct** | an enum is a closed vocabulary compared as case-folded text. Which case a model echoed a value back in is not information |
| PLAY-1001 | resolution_date | `"04.03.2026"` | **incorrect** | both numbers are ≤ 12, so this is 4 March in one country and 3 April in another. Refused rather than guessed |
| PLAY-1002 | resolution_date | `"19.03.2026"` | **correct** | no month is 19, so the form is unambiguous and normalises to 2026-03-19 |
| PLAY-1002 | loss_amount | `0.0` | **incorrect** | gold says `null` — the note states that no loss was recorded. "Zero" and "not stated" are different claims, and R7.3 scores the difference |

The two date rows are worth sitting with. A scorer that guessed day-first would
have been silently wrong for half of every year, and it would have been *right*
often enough that nobody would have found it. The code comment on `_as_date` says
the docstring always claimed the ambiguous form was refused, and that `/quality`
found the code guessing anyway — which is a small, real story about why "obvious"
behaviour still needs a test.

## Task 4 — the change gate

```console
$ dossier eval incident-audit --gold gold/incidents \
      --compare 20260917T210015Z-e8d2 20260917T210016Z-3069
compare 20260917T210015Z-e8d2 -> 20260917T210016Z-3069 · 4 documents · overall 100.0% -> 87.5% (-12.5)
  loss_amount        100.0%  75.0%  -25.0   <- regression
  resolution_date    100.0%  75.0%  -25.0   <- regression
  severity           100.0% 100.0%   +0.0
  affected_systems   100.0% 100.0%   +0.0
```

Both runs are reproduced from their own manifests and cache entries, so the
comparison asks no model, and both are scored against the same gold set. That is
what makes the delta a fact about your prompt edit rather than about the weather.

Adding a fifth note and trying to compare across it:

```console
$ dossier run incident-audit
warning: the source has moved since run 20260917T210016Z-3069: PLAY-1005.md new
run 20260917T211923Z-ae97 · …

$ dossier eval incident-audit --gold gold/incidents --compare 20260917T210015Z-e8d2 20260917T211923Z-ae97
incident-audit: runs 20260917T210015Z-e8d2 and 20260917T211923Z-ae97 cover different documents
-- only in 20260917T211923Z-ae97: PLAY-1005.md. A comparison over different documents is
not a comparison.
exit 2
```

Two safeguards in four lines, and they are different ones:

- The **warning at run time** (R4.9) is the one moment a person can notice that
  two runs are not over the same evidence, printed before any step runs so it is
  read rather than scrolled.
- The **refusal at compare time** (R7.8) is what stops the mistake being made
  anyway. The documents are checked before anything is scored, because a delta
  over different documents reports the documents' difference as the change's
  effect.

## Task 5 — what is not scored

With `affected_systems` removed from `PLAY-1003.json`:

```console
$ dossier eval incident-audit --gold gold/incidents
4 documents · 4 fields · overall 86.7%
  loss_amount         75.0%   <- weakest
  resolution_date     75.0%   <- weakest
  severity           100.0%
  affected_systems   100.0%
```

`affected_systems` is still 100.0% — it is now three verdicts instead of four,
all correct. The overall figure moved from 87.5% to 86.7% because the denominator
shrank from 16 verdicts to 15, not because anything got worse.

That is the whole difference between absent and `null`. A field nobody verified
contributes nothing in either direction; a field verified as "not stated" is
scored like any other answer. If absent were treated as `null`, removing a line
from a gold file would silently start marking runs wrong.

---

## What to take to your own project

- The gold set is the definition of correct. Attribute every answer, allow
  nothing from a run into it, and make it awkward to edit under pressure.
- Report per field, always. The blended figure is the one that hides the
  regression.
- Normalisation belongs in the scorer and must refuse ambiguity rather than
  resolve it. `07/08/2026` has no right answer.
- Comparing two runs over two different corpora is the most persuasive way to be
  wrong. Check the documents first, and refuse.
