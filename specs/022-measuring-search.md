# 022 — Measuring search

**Status:** Partially implemented
**Rules:** R22.1 – R22.8

## Purpose

`dossier search` ranks the documents of an index (spec 019), and nothing says
how well. Spec 019's two open questions, whether 100 candidates a list are
enough and whether the words list should match any word of the query, wait on
numbers. So does any move to BM25 or a reranker, and so does the live finding
that every single-word match ties at the same word rank, leaving the order to
the chunk id. This spec measures search against relevance gold: the questions
people really ask of an index, each with the documents a person judged to
answer it. The gold itself comes from the pilot, which writes about thirty real
questions and judges the first ten documents of each by hand (analysis_v2,
§4). This spec is the format, the measures and the command, so the pilot has
something to fill.

## Relevance gold

A directory a person names, holding one YAML file per query. The file's name,
without `.yaml`, names the query in what is printed and recorded.

```yaml
# gold/incidents-search/certificate-expired-at-checkout.yaml
query: certificate expired at checkout
readers: [incident-response]
judged_by: a.aleks
judged:
  incidents-jira:INC-4830: 2
  incidents-jira:INC-4821: 0
```

| Grade | Means |
|---|---|
| `2` | answers the question |
| `1` | related: worth seeing beside the answer |
| `0` | judged, and not relevant |

A document is named by its id in the index, `<source>:<key>` (spec 018), so a
key two sources share is not one document. Judgments are per document, because
search lists documents (R19.2). A document no judgment names is unjudged: it
gains nothing, as in every measure of this kind, and each query says how many
of its first ten are unjudged. Those are the holes a person fills next.

Each query names its readers, because a search names its readers (R19.11), and
what a reader may not read is not a miss. Each file is signed, because there is
no anonymous path into gold (R7.7).

## The command

```
dossier search incidents --gold gold/incidents-search
dossier search incidents --gold gold/incidents-search --json
```

Each query is searched as its file's readers, ten documents deep, and scored.
The command prints each query's measures, then their means over the queries
scored:

```
incidents · 1 query · nDCG@10 1.000 · recall@10 1.000
  certificate-expired-at-checkout  nDCG@10 1.000  recall@10 1.000  0 unjudged
```

It exits 0 whatever the scores: no bar gates anything until the pilot has
measured search once (open question 1). With tracking on it is one MLflow run
(R11.37), and each query's search is one trace, as any search's is (R11.35).

## The measures

**nDCG@10.** Each document in the first ten gains `2^grade - 1`, discounted by
`log2(rank + 1)`, its rank counted from 1. The sum is divided by the same sum
over the best order the query's judgments allow: its judged documents by grade,
highest first, the first ten. A grade 2 counts three times a grade 1, which is
what makes "answers it" and "related" different. 1.0 is the best order; 0.0 is
nothing relevant in the first ten.

**recall@10.** The share of the documents graded 1 or 2 that the search lists in
its first ten.

Both are computed in `domain/`, by functions of the ranked document ids and
the judgments, with no database and no model. They were checked once, on
2026-10-03, against `ir-measures` 0.4.3 (trec_eval, through
`pytrec-eval-terrier`) over this spec's rows and 200 random queries: 348
values, none differing by more than 1e-9. trec_eval's nDCG takes a grade as its
gain, so it was handed each grade as `2^grade - 1`, the gain used here.

## Existing options considered

| Option | Covers | Decision |
|---|---|---|
| MLflow's own (3.15.1, installed): `mlflow.metrics.ndcg_at_k` and `recall_at_k`; the `RetrievalRelevance` judge | The measures over RETRIEVER spans, and an LLM judge of relevance | Rejected. The classic measures are deprecated since 3.4 and count relevance as yes or no, losing the grades. The judge defaults to `openai:/gpt-4.1-mini`, a cloud API, asks outside dossier's model client, so nothing is cached and no calibration gate applies (R7.15), and it would put `mlflow` outside the tracking package (R0.19) |
| `ir-measures` 0.4.3 (Apache-2.0, Nov 2025) over `pytrec-eval-terrier` 0.5.10 (MIT, Oct 2025) | trec_eval's own definitions of nDCG, recall and the rest | Not adopted: it brings numpy and scipy for three formulas, and could not sit in `domain/`. Used once, outside the project, to check the formulas built here |
| `ranx` 0.3.21 (MIT, Aug 2025) | The same, with significance tests | Not adopted: numba, pandas, seaborn and ir-datasets for the same three formulas |
| Build: the measures as pure functions in `domain/` | nDCG@10 and recall@10 | Adopted, decided by `a.aleks` on 2026-10-03. The gold format, the readers, the command and the record are dossier's own whichever was chosen |

## Left out on purpose

- **Measuring variants.** `--candidates N` and matching any word, as options of
  the measurement only, are the next slice, before the pilot: with them the
  pilot answers spec 019's questions 1 and 2 on its own queries.
- **An LLM relevance judge.** Asked of a local model or through OpenWebUI only,
  and admitted through the calibration gate (R7.15), which needs human
  judgments to calibrate on. The pilot makes those first.
- **MRR**, the rank of the first relevant document. nDCG@10 already rewards it.
- **A bar** that fails the command. See open question 1.

## Open questions

| # | Question | Resolution |
|---|----------|------------|
| 1 | What mean nDCG@10 must search clear? | OPEN: needs the pilot's first measurement over its real queries, and the number is `a.aleks`'s to agree |

## Must hold

### R22.1 — a query's nDCG@10 is the graded gain of the documents listed, discounted by rank, over the best order its judgments allow

An unjudged document gains nothing. Gain `2^grade - 1`, discount
`log2(rank + 1)`, the ideal the judged documents by grade, the first ten.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.relevance.ndcg_at`)
- **Proved by:** `tests/unit/test_R022_1__ndcg_is_graded_gain_over_the_ideal_order.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira:INC-4830` graded 2, listed first; nothing else graded above 0 | `1.000` |
| 2 | the same, listed third, behind two unjudged documents | `0.500`: `3 / log2(4)` over `3` |
| 3 | `incidents-jira:INC-4821` graded 1 listed first, `incidents-jira:INC-4830` graded 2 second | `0.797`: `1 + 3 / log2(3)` over `3 + 1 / log2(3)` |
| 4 | *counter-example* — `incidents-jira:INC-4830` graded 2, listed eleventh | `0.000`: past the first ten, it gains nothing |

### R22.2 — a query's recall@10 is the share of the documents graded 1 or 2 that the search lists in its first ten

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.relevance.recall_at`)
- **Proved by:** `tests/unit/test_R022_2__recall_is_the_share_of_relevant_documents_listed.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira:INC-4830` graded 2 and `incidents-jira:INC-4821` graded 1; only `INC-4830` in the first ten | `0.500` |
| 2 | *counter-example* — a document graded 0 listed first, `INC-4830` graded 2 second | `1.000`: a 0 is judged and not relevant, and is no document to find |

### R22.3 — each query says how many of the documents in its first ten no judgment names

The holes in the gold, said rather than hidden: an unjudged document counts as
not relevant, so a high count means the score says little yet.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.relevance.unjudged`)
- **Proved by:** `tests/unit/test_R022_3__a_query_says_how_many_of_its_first_ten_are_unjudged.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | ten documents listed, three named by no judgment | `3 unjudged` |
| 2 | *counter-example* — every document listed judged, one of them graded 0 | `0 unjudged`: a 0 is a judgment |

### R22.4 — a query with no document graded 1 or 2 is named and left out of the means

Its nDCG has no ideal to divide by, and averaging it in as 0 would lower the
mean for a question nobody judged answerable.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.relevance.means`)
- **Proved by:** `tests/unit/test_R022_4__a_query_with_nothing_relevant_is_left_out_of_the_means.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | two queries, one with nDCG@10 `1.000`, the other with every judgment 0 | the second named `no relevant document judged`; the means over the first alone, `1.000` |
| 2 | *counter-example* — the second with one document graded 1 and not listed | scored `0.000`, and averaged in: the mean `0.500` |

### R22.5 — a relevance gold file that does not name a query, its readers, who judged it and grades 0 to 2 by document id is refused before any search, naming the file and the problem

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.relevance.RelevanceQuery`), config
- **Proved by:** `tests/unit/test_R022_5__a_malformed_relevance_file_is_refused.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira:INC-4830: 3` | refused: `certificate-expired-at-checkout.yaml: incidents-jira:INC-4830 is graded 3; a grade is 0, 1 or 2` |
| 2 | no `readers` | refused, naming the field: a search names its readers (R19.11) |
| 3 | no `judged_by` | refused, naming the field: there is no anonymous path into gold (R7.7) |
| 4 | `INC-4830: 2`, with no source | refused: a document is named `<source>:<key>` (spec 018) |
| 5 | *counter-example* — the file above, as written | read: one query, one reader, two judgments |
| 6 | `--gold gold/incidents-search`, a directory holding no `.yaml` file, or none at all | refused: `gold/incidents-search: no relevance gold in it (*.yaml)`; a measurement of nothing would print a mean of nothing |

### R22.6 — each query is searched as the readers its file names, and a judgment of a document none of them may read is refused

A document a query's readers may not read is never listed for them (R19.10),
so judging it relevant would count a miss the search was right to make.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.relevance`)
- **Proved by:** `tests/acceptance/test_R022_6__a_query_is_searched_as_its_readers.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `readers: [incident-response]` | searched as `incident-response`: its trace names `["incident-response"]` (R11.35) |
| 2 | `readers: [sre]`, judging `incidents-jira:INC-4830`, which `incidents-jira`'s `acl` gives to `incident-response` alone | refused before any search, exit 2: `certificate-expired-at-checkout.yaml: incidents-jira:INC-4830 is not readable by sre` |
| 3 | *counter-example* — `readers: [incident-response, sre]` | searched as both: one of them may read it |

### R22.7 — `dossier search INDEX --gold DIR` prints each query's nDCG@10, recall@10 and unjudged count, then the means

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.search`)
- **Proved by:** `tests/acceptance/test_R022_7__search_gold_prints_each_querys_measures.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `gold/incidents-search` holding `certificate-expired-at-checkout.yaml` as above, and the index listing `INC-4830` first | `incidents · 1 query · nDCG@10 1.000 · recall@10 1.000`, then `  certificate-expired-at-checkout  nDCG@10 1.000  recall@10 1.000  0 unjudged`; exit 0 |
| 2 | the same, `--json` | one JSON object: `index`, the means, and `queries`, each with its name, `query`, `readers`, `ndcg_at_10`, `recall_at_10`, `unjudged` and the document ids listed |
| 3 | *counter-example* — the index listing `INC-4830` nowhere in its first ten | `nDCG@10 0.000`, and still exit 0: no bar gates anything yet (open question 1) |

### R22.8 — `--gold` with a query, a reader, `--where`, `--chunks` or `--limit` is refused, naming both

Each would change what is measured: the gold's files are the queries and name
their readers, and the measures are of ten documents, unfiltered.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.search`)
- **Proved by:** `tests/unit/test_R022_8__gold_takes_no_query_or_reader.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier search incidents "certificate expired at checkout" --gold gold/incidents-search` | exit 2, before anything is read: `--gold cannot be combined with a query: the gold set's files are the queries` |
| 2 | `--gold gold/incidents-search --as sre`, or `--all-readers` | exit 2: `--gold cannot be combined with --as: each query names its readers` |
| 3 | `--gold gold/incidents-search --where component=checkout`, `--chunks` or `--limit 5` | exit 2, naming the option: it changes what is measured |
| 4 | *counter-example* — `--gold gold/incidents-search --json` | measured, and printed as JSON |
