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
