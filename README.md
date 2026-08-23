# dossier-audit

Document collection and audit pipeline. Syncs documents from configured sources,
freezes them as immutable snapshots, runs a sequence of prompt stages over them,
and scores the results against human-verified answers.

Package and CLI: `dossier`.

- `CLAUDE.md` — the working agreement for this repository
- `specs/` — the source of truth. Read `specs/000-overview.md` first.
- `KICKOFF.md` — prompt for the first implementation session
- `docs/` — background material, including the design deck

## Commands (target shape)

```
dossier sync <pipeline>              # fetch only what changed
dossier run <pipeline> --plan        # what would run, and why
dossier run <pipeline>               # execute
dossier eval <pipeline> --gold …     # score against verified answers
dossier eval <pipeline> --compare a b
dossier run --replay runs/<id>/      # reproduce a past run exactly
```
