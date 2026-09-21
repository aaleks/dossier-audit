# Proposal — two things exercise 11 walked into

A worked example of the shape ground rule 1 asks for. Exercise 04 wrote one of
these, it was reviewed, and it landed as R8.10. This one is **not** written as
though it were agreed: it is the thing you hand to review, and the second half
argues partly against itself.

Write your own before reading this. Comparing two proposals is the exercise;
copying one is not.

---

## 1. An issue payload has no converter, and the pair it needs is not `application/json`

### What happened

`dossier sync jira-audit` held four issues at `application/json` and one
attachment at `text/markdown`. `dossier convert jira-audit` then refused the
whole source:

```
4 document(s) have no converter:
  PLAY-1 (application/json): nothing converts application/json to markdown
  ...
```

Refusing all five rather than converting the one is right, and spec 008 says so:
every document is resolved before any is converted, so "half a source converted"
is not a state that exists (R8.5, R8.6). Nothing is broken. The source simply
cannot be audited, and it is the most common source a person would point
`dossier` at.

### What is tempting and wrong

Ship a converter claiming `(application/json, markdown)` inside `dossier`.

The pair is the whole type. A converter that claims `application/json` claims
**every** JSON document any connector ever holds — a webhook body, a config
export, a GeoJSON file — and renders all of them as though they were Jira
issues. A pair matches at most one converter (`_claims` in
`domain/conversion.py`), so that converter would also make it impossible for
anyone else to claim JSON without uninstalling it. The blast radius is every
future source.

It is also an authorship question spec 008 has already answered once: a format
that only one source produces is what R8.7 put behind an entry point, so that
claiming it is an installation and not an edit to `dossier`.

### What is proposed

Nothing in `src/`, and one paragraph in spec 008.

`solution/dossier_jira_playground/` claims the pair from **outside**, which is
what the entry-point group is for. That is the honest fix for one person's Jira
and it needs no rule.

What is missing is not a converter; it is a **sentence saying this is the
answer**. Someone meeting the refusal above has no way to know whether they hit
a gap dossier intends to close or a decision dossier has made. Proposed
amendment to spec 008, as a note under R8.5 rather than a new rule:

> A media type that several unrelated sources produce in unrelated shapes —
> `application/json` is the example — is deliberately unclaimed by `dossier`.
> The pair is the unit of claiming, and a converter claiming a container format
> claims every document in it. Such a pair is claimed by an installed package
> (R8.7), never by `dossier`.

**Why a note and not a rule.** It is not testable, and `specs/README.md` says a
rule is an invariant that is testable. It documents a decision already forced by
R8.5 and R8.7 together. If review wants it enforceable, the testable form is a
different claim — *no converter shipped in `dossier` claims a media type in a
declared container-format list* — and that is a rule with a maintained list in
it, which is a cost worth naming before paying.

### Counter-example the note must survive

`application/pdf` is a container too, and `dossier` ships `pdf-markdown` for it.
The difference the note has to carry: a PDF has one reading — pages of text —
whatever produced it. A JSON payload has no reading at all until you know which
system wrote it. If review does not accept that distinction, the note is wrong
and the honest answer is that `dossier` has no position here.

---

## 2. `fields:` cannot express a projection over a Jira issue

### What happened

`sources.yaml` declares `fields: [key, fields]`, and the exercise's task 5 shows
why that is nearly the only thing it can declare. `domain.sync.normalise`
projects onto **top-level** keys:

```python
projected = {name: document[name] for name in sorted(fields) if name in document}
```

A Jira issue payload has four top-level keys that matter — `expand`, `id`,
`self`, `fields` — and everything a person would call content is nested under
the last one, `updated` included. So:

- `fields: [key, fields]` excludes `self` and `expand`, which is real: moving
  the instance to another hostname, or upgrading it, no longer re-snapshots
  every issue. That is worth having.
- Nothing finer is expressible. `updated` is inside the projection, so every
  no-op edit — adding a label, someone watching the issue — still moves the
  content hash and writes a new snapshot of a document nobody changed.
- `fields: [key]` is the only alternative and is worse: a real edit to the
  description becomes invisible, which is the failure R2.10 exists to prevent.

R2.10 is not wrong and nothing here contradicts it. The projection does what the
spec says. It is the *expressiveness* that does not reach the payload shape of
the most common remote source.

### What is proposed

Dotted paths in `fields:`, so that `fields: [key, fields.summary,
fields.description, fields.status]` means what it looks like.

Sketch, to be argued rather than accepted:

- A name with no `.` behaves exactly as today. Existing sources are untouched,
  and `source_config_hash` over `["key", "fields"]` is unchanged, so no held
  document is re-evaluated by the upgrade itself (R2.3 would otherwise fire on
  every source).
- A name with `.` walks the object. A path that is absent stays absent, which is
  the rule `in`-not-`.get` already keeps (an absent field and an explicit null
  are different things and must not hash alike).
- A path through a non-object is an error against that document, named, at the
  same place the "needs a JSON object" error is raised now.
- Arrays are the open question and the reason this is a sketch. `fields.comment.comments`
  is a list; `fields.attachment[0].id` is a path language, and a path language
  in a YAML key is how a configuration format becomes a programming language.
  The narrow version — dotted paths through objects only, lists taken whole or
  not at all — is probably the one to propose, and it should be argued before
  it is written.

### What this is worth

Concretely: one no-op edit to a Jira issue currently costs a fetch, a hash, a
snapshot write and a convert of every artifact downstream of it. On a project
where a bot touches issues nightly, that is the entire source re-snapshotted
every day, for content that did not change. Everything downstream is still
correct — it is a cost, not a defect, which is exactly why it would go unnoticed.

### What would say this is not worth doing

If the answer is "declare `fields:` over the issue and accept the churn", that is
defensible and costs nothing to decide. This proposal should be rejected on that
ground rather than left open, because an open proposal reads like a promise.

---

## How to take either of these further

Not by implementing them. `/discover` turns an agreed need into rules with
examples and counter-examples, and it is the step that would come next — after a
human has said which of the two, if either, is worth a rule at all.
