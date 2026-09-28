# Use case two, on paper

The business case for `dossier` is not the incident audit. It is the claim in the
design deck that the *second* audit costs an afternoon:

> A new audit in an afternoon. Three prompt files and a short configuration
> block. Written by an analyst, no developer needed.

Nothing built so far tests that claim. This is a paper exercise against a
genuinely different document type, done before the configuration format is
hardened any further. If the format does not fit, it is far cheaper to find out
at 15 rules than at 60.

**Nothing here is a specification.** It is a design review of specs 001 and 003
using a second example, and it ends with three findings.

---

## The candidate: supplier contract renewal audit

Legal wants to know which supplier contracts auto-renew, when notice must be
given, and where liability is capped. Today someone reads them.

The documents are unlike incident reports in ways that matter:

| | Incident audit | Contract audit |
|---|---|---|
| Source | Jira issues, a manual folder | A SharePoint/folder of signed PDFs |
| Shape | Structured fields plus prose | Prose and tables, scanned pages |
| Length | One to three pages | 20–60 pages, plus amendments |
| Fields | Amounts, dates, an enum, a narrative | Dates, durations, money, booleans, jurisdiction |
| Verified by | Incident manager | Legal counsel |
| Unit | One issue = one document | **One contract = a master plus N amendments** |

## What the configuration would look like

```yaml
# sources.yaml -- one new block
  - id: contracts-signed
    type: folder
    path: inbox/contracts/
    convert: [markdown, page_images]
```

```yaml
# pipelines/contract-renewal/pipeline.yaml
sources:   [contracts-signed]
reference: [policy-confluence]
gold:      gold/contracts/

model:     anthropic:claude-sonnet-4-5-20250929

steps:
  - id: extract
    prompt: prompts/01_extract.md
    input: documents
    mode: per_file
    output: schemas/contract.json

  - id: verify
    prompt: prompts/02_verify.md
    input: [documents, extract, reference]
    mode: per_file
    output: schemas/contract.json

  - id: report
    prompt: prompts/03_report.md
    input: verify
    mode: aggregate
```

That is the same shape as `incident-audit`, with a different schema and different
prompts. **The format holds for the common case**, which is the main thing this
exercise set out to check.

Three things it does not hold for.

---

## Finding 1 — there is no way to say "these files are one document"

**The blocker.** A supplier contract is a master agreement plus amendments, and
the renewal date is in amendment 3 while the liability cap is in the master. A
question about the contract cannot be answered from either file alone.

`mode: per_file` runs one model call per document and produces one artifact per
document. `mode: aggregate` runs one call over *everything*. There is nothing in
between, and "everything" is the wrong answer at 400 contracts: it is one enormous
call, it destroys per-document caching (R5.7), and it makes per-document scoring
meaningless (R7.2).

The same gap exists in the incident audit and is currently hidden. R1.6 says
attachments are addressed and versioned independently — but nothing says whether a
stage reading `documents` sees an issue and its attached PDF as one document or
two. Spec 003 does not answer it, and the incident slice has not had to.

*Suggested resolution:* a third mode, or a grouping key on the source —
`group_by: contract_id` — with `per_group` alongside `per_file`. That is a spec
amendment to 003 and 004, and it should be discovered properly rather than
designed here. **Worth raising before more of 004 and 005 is built**, because a
group is a cache-key input and retrofitting one into key composition is expensive.

*Resolved by R3.15.* `per_group` is the fourth mode, and it needed no grouping
key. A document's group is its key up to the first `/`, and every connector
already keys a file under what it belongs to. So a contract kept in its own
subfolder is a group, and so is a Jira issue with its attachments. The group's
name is in the key, along with every member's inputs and no other document's
(R5.14). Its fields cite a member (R6.22), it is scored against a gold answer for
the group (R7.32), its judge is shown every member (R7.33), and a replay
recomposes it from the manifest (R4.15). Contracts told apart only by a filename
convention in one flat folder are sorted into subfolders first. Spec 003's
"Existing options considered" says why the group comes from the key and not
from a setting on the source. Playground exercise 16 runs this contract.

## Finding 2 — the field record does not carry a type

Spec 006's field record has `value`, `currency`, `source`, `confidence`. Spec 007
picks a scorer by "field kind": amount, date, reference, enum, evidence span,
free text. Nothing says where that kind comes from.

R6.7 says the pydantic model generates the schema, the validation *and the
scorer's field list*, so the answer is presumably "the model's field type". That
works for `date` and `amount`. It does not distinguish `notice_period_days: 90`
(a duration, where 90 and "3 months" are the same answer) from `contract_value:
90` (where they are not). And a boolean `auto_renew` has no scorer listed in
spec 007 at all.

*Suggested resolution:* an explicit scorer annotation per field in the schema
model. Small, and it belongs to spec 007 rather than 006.

*Resolved by R7.36 – R7.39,* and with one correction to the finding. A field's
`kind` in its YAML declaration already was the scorer annotation (R6.10); what
was missing was the kinds. `auto_renew: {kind: boolean}` is scored by its truth
value, and `notice_period: {kind: duration}` by its length. But 90 days and
"3 months" are **not** the same answer: a month is 28 to 31 days, so three
months' notice and ninety days' notice are different notice, and R7.38 scores
the pair incorrect and says why. A count such as `contract_value: 90` is an
`amount` with no currency.

## Finding 3 — "an analyst, no developer needed" is not yet true

Adding this use case needs a `schemas/contract.json` written as a pydantic model
(R6.7), because the model is what generates the schema, the validation and the
scorer list. That is a Python file, not YAML.

The deck's claim is a *product* claim, and it is currently false for anything
that is not a prompt change. Either the claim needs narrowing — "a new audit over
an existing schema" — or schemas need a declarative form.

*This is the finding I would take to the next management review*, because it is
the one that changes the cost of use cases three through ten, which is the whole
argument for building this.

*Resolved by R6.10.* Schemas now have the declarative form: a step's `output`
names a YAML field declaration (`schemas/contract.yaml`, not `contract.json`),
and the JSON Schema and scorer list are generated from it. R6.7, which required
the pydantic model, is superseded. The pipeline above still reads `contract.json`
because it records what was true when this finding was written.

---

## What this exercise did not find

Worth saying, because a review that only produces problems is not a review:

- `sources.yaml` and `pipeline.yaml` needed **no new keys** for the common case.
- The four-stage pipeline (ingest, extract, verify, report) fits unchanged.
- Grounding by evidence span works better here than for incidents, not worse —
  contracts are quotable, and a span pointing at page 34 is exactly what makes a
  reviewer's job fast (spec 006).
- Nothing about the hash boundary, the ledger or caching is strained.

The architecture holds. It is the *document model* — one item equals one
document — that does not, and that is a spec conversation rather than a rewrite.
