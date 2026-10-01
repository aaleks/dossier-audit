# Servers to run dossier against

(Also here: `dev/mutation/`, the mutation-testing runner for `domain/`. It has its
own README.)

A Jira and a Confluence, each Data Center in Docker, for running a source
against a real server you can write to: before a slice that talks to one is
called done (CLAUDE.md), or to try `dossier sync` somewhere a public server will
not let you change what it holds. Nothing here is part of `dossier`, and no test
uses it.

| | Compose file | Address | Image | RAM, capped |
|---|---|---|---|---|
| Jira | `dev/jira/docker-compose.yml` | <http://127.0.0.1:8091> | `atlassian/jira-software:10.3.25` | 3.8 GB |
| Confluence | `dev/confluence/docker-compose.yml` | <http://localhost:8090> | `atlassian/confluence:9.2.21` | 3.5 GB |

The images are pinned, as the model in `pipeline.yaml` is: a floating tag would
make "the server this was checked against" unknowable. The caps are there
because the machine these were first run on has an 8 GB WSL VM shared with
other stacks, and Confluence's first boot hung it until they were set. On a
machine like that, run one of the two at a time.

## Bringing one up

```bash
docker compose -f dev/confluence/docker-compose.yml up -d
docker compose -f dev/confluence/docker-compose.yml logs -f confluence
```

The first boot takes a few minutes. Then open the address above and work
through the setup wizard. The database is already set from the compose file,
and the wizard asks for two things:

1. **A licence.** Data Center has no free tier: take a free 30-day evaluation
   licence from my.atlassian.com, against the Server ID the wizard shows.
2. **The administrator account.** Write the username and password down
   somewhere you will find them. Nothing in this folder records them: the
   wizard stores them in the server's own database, and a server whose login
   nobody kept can only be reset or rebuilt.

`down` stops a server and keeps its data. `down -v` deletes the volumes, so
the next `up` starts again at the wizard.

## Pointing dossier at it

Name the credential's variables in `sources.yaml` and put the values in `.env`
beside it, never in the YAML (R1.8). `.env.example` has the variables.

```yaml
# sources.yaml
sources:
  - id: local-confluence
    type: confluence
    url: http://localhost:8090
    query: space = DEMO                   # a space key you created
    token_env: DOSSIER_CONFLUENCE_TOKEN

  - id: local-jira
    type: jira
    url: http://127.0.0.1:8091
    query: project = DEMO
    token_env: DOSSIER_JIRA_TOKEN
```

Either server takes a personal access token alone, sent as Bearer: create one
from your profile, under *Personal Access Tokens*. To use the administrator's
password instead, also name `user_env: DOSSIER_CONFLUENCE_USER` (or
`DOSSIER_JIRA_USER`) and the pair is sent as HTTP Basic (R1.12, R1.21).

```
# .env
DOSSIER_CONFLUENCE_TOKEN=<the token>
DOSSIER_JIRA_TOKEN=<the token>
```

`playground/11-a-real-jira-on-your-machine/seed_jira.py` fills a Jira with
issues and attachments to sync. It reads `DOSSIER_JIRA_URL`, so for this Jira
set `DOSSIER_JIRA_URL=http://127.0.0.1:8091`. That exercise brings up its own
Jira on port 8080, where the project's default model is served on this setup
(`.env.example`); this one is on 8091 so the two do not collide.

## The embedding index

A PostgreSQL with pgvector, for `dossier embed` to write an index into (spec
018). Unlike the two above, a test uses it: the live test of the Postgres index
sink, `tests/integration/test_R018_4__postgres_index_sink.py`, which writes into
a schema of its own and drops it.

```bash
docker compose -f dev/index/docker-compose.yml up -d
docker compose -f dev/index/docker-compose.yml ps        # wait for (healthy)
```

It needs no setup: the user, the password and the database are all `dossier`,
and `dossier` creates its schema, `dossier_index`, on the first embed. Point an
index at it with the variable its `target.dsn_env` names, in `.env`:

```
DOSSIER_INDEX_DSN=postgresql://dossier:dossier@127.0.0.1:5435/dossier
```

Port 5435, because the machine this was first run on already had PostgreSQLs
on 5432, 5433 and 5434. RAM is capped at 512 MB. The image,
`pgvector/pgvector:pg17`, is a floating tag, unlike the two above: it served
PostgreSQL 17.10 with pgvector 0.8.6 at the first live check.

The driver is the `index` extra: `uv sync --extra index`, or `--all-extras`.

```bash
DOSSIER_INDEX_DSN=postgresql://dossier:dossier@127.0.0.1:5435/dossier \
  .venv/Scripts/python.exe -m pytest -m live tests/integration/test_R018_4__postgres_index_sink.py
```
