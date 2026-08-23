# Kickoff prompt for the first Claude Code session

Paste everything below into a fresh session at the repo root.

---

Read `CLAUDE.md` and every file in `specs/` before writing anything. They are the
source of truth for this project; the code is an implementation of them.

Then, before any code:

1. List anything in the specs that is ambiguous, contradictory or missing for the
   slice below. Propose exact wording for each. Wait for my answer.
2. Propose the package layout and the dependency list, with one line per
   dependency saying why it is there.

Once I have replied, build **one vertical slice only**:

- `folder` connector (spec 001)
- ledger + content-addressed snapshot store (spec 002)
- a pass-through markdown converter (spec 005 key composition applies)
- config loading and validation for `sources.yaml` and `pipeline.yaml` (spec 003)
- step resolution, manifest freezing and `--plan` (spec 004)
- one `extract` stage against a **fake model client** returning canned responses
- schema validation, span checking and abstention (spec 006)
- deterministic scorers and `dossier eval` over a tiny gold set (spec 007)

Explicitly out of scope for this slice: Jira, Confluence, PDF conversion, page
images, MLflow, LLM judges, real model calls.

Definition of done:

- `dossier sync`, `dossier run --plan`, `dossier run`, `dossier eval` all work
  end-to-end against fixtures in `tests/fixtures/`
- every `Must hold` rule touched by this slice has a test named
  `test_R<spec>_<rule>__<description>`
- `pytest` passes offline, with no network and no model calls, in under 10 seconds
- running `dossier run` twice in a row performs zero model calls the second time

Work in small commits. Write the tests from the specs before the implementation.
If you find yourself needing behaviour that no spec describes, stop and propose a
spec amendment rather than inventing it.
