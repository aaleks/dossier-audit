# Servers to run dossier against

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
