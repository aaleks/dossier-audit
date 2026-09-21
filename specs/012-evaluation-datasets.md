# 012 — The gold set as an MLflow evaluation dataset

**Status:** Partially implemented
**Rules:** R12.1 – R12.6

## Purpose

A gold set is the asset every score `dossier` reports is a claim about, and until
now it existed only as files in git and a 64-character tag on an eval run
(R11.3 row 2). MLflow holds evaluation datasets as first-class objects, so this
spec says how a gold set is published as one: a named, versioned thing with one
record per verified document, which an eval run links to as its input. Without it
the question "which answers was this figure measured against" is answerable only
by taking a hash to a git log, and two evals of the same pipeline are comparable
in the terminal and nowhere else.

The dataset is a **projection**, one way only. It is written from `gold/` and
read by a person looking at MLflow; no score, key, manifest or provenance record
is ever computed from it (R12.4). That is the same promise R10.4 makes for
tracking as a whole, restated here because a dataset looks much more like an
input than a metric does.

## The command

```
$ dossier dataset publish incident-audit --gold gold/incidents
incidents · 4 records · digest 61da2705
published to MLflow: dossier-audit/incident-audit/eval/incidents
```

Its own command rather than a flag on `dossier eval`, because publishing a gold
set and scoring a run fail for different reasons and are run at different times:
a gold set is published when a reviewer has agreed new answers, and scored
against on every run after that. An eval that published as a side effect would
also mutate shared tracking state on a command whose whole contract is that it
reads (R0.11 row 5).

The experiment is the one the eval for that gold set records to — rendered from
`DOSSIER_MLFLOW_EXPERIMENT_EVAL` by R10.2, so the dataset sits beside the runs
measured against it rather than in a namespace of its own.

## What a record holds

One record per gold document, whose unit is the document — the unit of a cache
key, a trace and a score everywhere else in `dossier`:

```json
{
  "inputs": {
    "document": "INC-4821"
  },
  "expectations": {
    "loss_amount": 48200.0,
    "resolution_date": "2026-07-28",
    "severity": "major",
    "root_cause": null
  },
  "tags": {
    "dossier.snapshot": "a3f9c1e2…"
  }
}
```

`inputs` holds the document key and **nothing else**, because MLflow merges a
record onto the SHA-256 of its `inputs`: whatever goes in there is the identity of
the record. The snapshot address the answers were verified against is a record
*tag* for that reason. Were it an input, a document repointed to new content
(R2.18) would merge onto nothing and appear as a fifth record beside its own
older self, and R12.3's claim that the document is the merge key would be false.
It also means a gold set is publishable before anything has been synced: a
document with no ledger row is published without the tag rather than refused.

`expectations` are the verified answers, and nothing else. No run's output goes in: a dataset holding what one run produced
changes every time a different run is scored, and a yardstick that moves is not
one. The run's answers are already in MLflow, as the metrics and traces of the
eval that produced them (R11.3).

`root_cause` is `null` above because `INC-5455`'s reviewer recorded an
abstention, and it is carried rather than dropped (R12.2). A field absent from
`expectations` reads as a field nobody verified, which R7.3 row 4 treats as a
different thing entirely from a field verified as having no answer.

The digest a publish prints is MLflow's own, computed over the records. It is
not the gold set hash `3b7e1d90` that tags the dataset and the eval run: the two
move together and are different values, and a spec example showing one where the
other belongs would be transcribed straight into a test.

A reviewer's `verified_by` and `verified_at` are dataset **tags**, not
expectations. They are attribution for the set, not answers in it.

## Where the code sits

Publishing returns three things a `Tracker` may not return — a dataset id, a
digest and how many records were added — and `Tracker`'s contract is that every
method sends and returns nothing, which is how R0.10 justifies letting it near
the network at all. So the registry is a **second port**, `DatasetRegistry` in
`domain/ports.py`, implemented in `dossier.infrastructure.tracking` beside the
tracker:

```
domain/datasets.py        the projection: gold documents -> records, pure
domain/ports.py           DatasetRegistry: publish(...) -> Published, find(name)
infrastructure/tracking/  the mlflow.genai.datasets calls
```

What it returns may reach an MLflow tag and a line in the terminal, and nothing
on disk (R12.4 row 3). A `FakeDatasetRegistry` in the default suite counts
publishes and records as `FakeTracker` counts runs and `FakeModelClient` counts
calls.

Evaluation datasets need a tracking server with a SQL backend; a FileStore has
no `/api/3.0/mlflow/datasets` to call. That is a machine's configuration, so it
is refused by name at startup like an unreachable server (R12.5, R10.5).

## Must hold

### R12.1 — a gold set publishes as one dataset named after it, with one record per gold document

The name is the gold directory's own — `gold/incidents` publishes as
`incidents`, the name R10.2 already renders `{gold}` from — so the dataset a
person opens and the tag on the eval run beside it read as the same thing.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.datasets.publish_gold`)
- **Proved by:** `tests/acceptance/test_R012_1__a_gold_set_publishes_as_one_dataset.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier dataset publish incident-audit --gold gold/incidents`, holding `INC-4821`, `INC-4822`, `INC-4901`, `INC-5455` | 1 dataset `incidents` in `dossier-audit/incident-audit/eval/incidents`, 4 records; tagged with the gold set's full 64-character hash `3b7e1d90…` (R0.7) and `a.aleks` |
| 2 | the same | the terminal names the dataset, its record count and its digest; exit 0 |
| 3 | *counter-example* — `gold/empty/`, a directory holding no `<document>.json` | exit 2 naming the directory; 0 datasets created, 0 records sent. A dataset of nothing would read as a gold set nobody has filled in yet, which is what the empty directory already says |

### R12.2 — a record's only input is the document key, its expectations are the verified answers, and its snapshot is a tag

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.datasets.record_for`)
- **Proved by:** `tests/unit/test_R012_2__a_record_holds_the_document_and_its_verified_answers.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821`, verified `loss_amount` 48200.00 CHF, `resolution_date` 2026-07-28, `severity` `major`, held at snapshot `a3f9c1e2` | `inputs` `{document: INC-4821}`; `expectations` those three fields by their declared names; `tags` `{dossier.snapshot: a3f9c1e2…}` |
| 2 | `INC-5455`, whose `root_cause` is `null` with reason "only competing hypotheses" (R7.3) | `expectations.root_cause` is `null`, present. A field nobody verified is absent, and the two must stay distinguishable (R7.3 row 4) |
| 3 | a gold document whose key the ledger holds no row for — answers verified for something never synced | `inputs` `{document: …}` and no `dossier.snapshot` tag; published, not refused. The snapshot is provenance for the answers, not a precondition for having them |
| 4 | *counter-example* — the same document's `verified_by` `a.aleks` and `verified_at` `2026-08-14` | in neither `inputs` nor `expectations`; attribution for the set, carried as a dataset tag (R12.1 row 1) |
| 5 | *counter-example* — the answers the scored run produced for `INC-4821` | not in the record. A dataset that moves with the run being measured is not a yardstick; the run's answers are its own eval's metrics (R11.3) |

### R12.3 — republishing an unchanged gold set adds no record and leaves the digest unchanged

Records are merged on the document their `inputs` name -- MLflow's key is the
SHA-256 of `inputs`, and the document key is all that is in there (R12.2) -- so
publishing is idempotent, and publishing twice is a no-op a person can run
without thinking about it.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.datasets.publish_gold`)
- **Proved by:** `tests/unit/test_R012_3__republishing_an_unchanged_gold_set_changes_nothing.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gold/incidents` published, then published again with no file changed | 1 dataset, 4 records, the same digest `61da2705`; 0 datasets created the second time |
| 2 | `INC-4822`'s `resolution_date` corrected by a reviewer (R7.7), then published | still 4 records — the document is the merge key, not the answer — and a new digest |
| 3 | a fifth document `INC-4830` verified and published | 5 records, a new digest; the four already there unchanged |
| 4 | `INC-4822` repointed from `0e52dd18` to `77c1b40a` by a sync (R2.18), then published | still 4 records, `INC-4822`'s `dossier.snapshot` tag updated in place. A record keyed on its snapshot as well would leave one document holding two records, one of them addressing content the store no longer serves |
| 5 | *counter-example* — a gold file rewritten with the same answers formatted differently | a new digest, because the gold set hash is over bytes (R0.7) and the set it addresses has moved. A digest that ignored the rewrite would claim a set nobody can reproduce |

### R12.4 — a dataset is a projection of `gold/`, and no score, key or file is ever computed from it

The one-way promise this spec opens with. A dataset is read by a person, never by
`dossier`.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/unit/test_R012_4__a_dataset_is_never_read_back_into_a_score.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `gold/incidents` published, then `INC-4821`'s `severity` edited in the file and `dossier eval` run without republishing | the edit is scored; the stale dataset contributes nothing to any figure (R11.7 says what is said about it) |
| 2 | the dataset `incidents` present and `gold/incidents/` deleted | `dossier eval` exits 2 naming the directory; a dataset is not a gold set and cannot stand in for one |
| 3 | a dataset published, its id `d-18afc31376cb427a` returned | reaches an MLflow tag and the terminal line; no file under `runs/`, `gold/` or `.dossier/` holds it (R10.4 row 2) |
| 4 | *counter-example* — the same eval with tracking off entirely | byte-identical scores and the same exit code; publishing and linking change no output (R10.4 row 1) |

### R12.5 — publishing with tracking off, or to a server that cannot hold a dataset, is refused by name before anything is sent

Both are a machine's configuration, and both are refused where R10.5 refuses an
unreachable server: at startup, naming the thing to fix.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main`)
- **Proved by:** `tests/acceptance/test_R012_5__publishing_is_refused_by_name.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_MLFLOW_ENABLED=false`, `dossier dataset publish incident-audit --gold gold/incidents` | exit 2 naming `DOSSIER_MLFLOW_ENABLED`; 0 requests sent. Unlike a run, this command has nothing to do with tracking off — its whole output is the record |
| 2 | tracking enabled against a FileStore server, whose `/api/3.0/mlflow/datasets` is absent | exit 2 naming the SQL backend a dataset needs; 0 records sent |
| 3 | tracking enabled, nothing answering at `http://localhost:5000` | exit 2 naming the URI, as R10.5 row 1 refuses a run |
| 4 | tracking enabled, the `tracking` extra not installed | exit 2 naming `dossier[tracking]` (R10.5 row 3) |
| 5 | *counter-example* — `dossier eval incident-audit --gold gold/incidents` against that same FileStore server | scores and exits 0, with no dataset link. An eval needs no dataset; only publishing does |

### R12.6 — one gold set is one dataset, and a second pipeline publishing it adds its experiment rather than a second dataset

A gold set is a workspace asset and can serve several pipelines (R3.7), while a
dataset is named by MLflow globally. So the name follows the gold set, and the
pipeline follows R10.2 into the list of experiments the one dataset belongs to.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.datasets.publish_gold`)
- **Proved by:** `tests/unit/test_R012_6__one_gold_set_is_one_dataset_across_pipelines.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gold/incidents` published for `incident-audit`, then for `postmortem-review` | 1 dataset `incidents`, 4 records, belonging to both `dossier-audit/incident-audit/eval/incidents` and `dossier-audit/postmortem-review/eval/incidents`; 0 datasets created the second time |
| 2 | `gold/observability` published for `incident-audit` | a second dataset `observability`; one name per gold set, not per pipeline |
| 3 | *counter-example* — an experiment template with no `{gold}`, so both pipelines render `dossier-audit` | the one dataset belongs to that one experiment, listed once. A template that collapses two experiments does not make two datasets (R10.2) |
