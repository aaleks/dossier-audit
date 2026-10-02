#!/usr/bin/env bash
# PreToolUse: refuse edits that break the project's hard rules.
#
# Exit 2 blocks the tool call and returns stderr to Claude as feedback.
# Exit 0 allows it. Anything else is a hook error, not a block.
#
# Kept deliberately small. Rules needing real parsing belong in
# tests/architecture/ where they can be debugged; a hook is for the mistakes
# that are cheap to detect now and expensive to discover later.

set -uo pipefail
payload=$(cat)

# jq is not guaranteed on Windows, so pull the path out with grep.
path=$(printf '%s' "$payload" \
  | grep -oE '"file_path"[[:space:]]*:[[:space:]]*"[^"]+"' \
  | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
[ -z "$path" ] && exit 0

# Normalise Windows separators so one pattern matches both forms.
norm=$(printf '%s' "$path" | tr '\\' '/')

# 1. Secrets are never edited by an agent, only by a human.
case "$norm" in
  *.env|*/.env|*.pem|*.key)
    echo "BLOCKED: $norm holds live credentials." >&2
    echo "Edit it yourself and tell me what changed." >&2
    exit 2
    ;;
esac

# 2. Verified answers are a human decision.
#    The failure mode of eval-driven work is "the score dropped, so adjust the
#    expected answer". That silently lowers the bar and leaves the suite green.
#    R7.7 says corrections are attributed; an agent has nobody to attribute to.
case "$norm" in
  */gold/*|gold/*|*/tests/evals/golden/*|tests/evals/golden/*)
    echo "BLOCKED: verified answers are changed by a human, not by an agent." >&2
    echo "Editing gold until a score passes is how a threshold dies (R7.7)." >&2
    echo "Propose the cases and let the user write them." >&2
    exit 2
    ;;
esac

# 3. The resolved lockfile changes via uv, not by hand.
case "$norm" in
  *uv.lock)
    echo "BLOCKED: uv.lock is generated. Edit pyproject.toml and run 'uv sync'." >&2
    exit 2
    ;;
esac

# 4. Snapshots are immutable (R0.2). Nothing under a snapshot store is ever
#    rewritten -- new content means a new content-addressed path.
case "$norm" in
  */.dossier/snapshots/*|.dossier/snapshots/*)
    echo "BLOCKED: snapshots are immutable (R0.2)." >&2
    echo "New content means a new content-addressed path, never an edit." >&2
    exit 2
    ;;
esac

# 5. The hash boundary (R0.19, which superseded R0.19, R0.16, R0.10, R0.9 and R0.1).
#    Four packages may import a network client: connectors fetch source
#    payloads, models ask a model, tracking sends records to MLflow, and index
#    writes and searches the embedding index.
#    tests/architecture catches this too, but catching it at write time saves a
#    red run and explains the reason.
#
#    Grep the raw JSON payload: written content arrives as a JSON string with
#    newlines escaped, so an import statement still appears verbatim.
case "$norm" in
  src/dossier/infrastructure/connectors/*|*/src/dossier/infrastructure/connectors/*)
    : # left of the boundary -- network is this package's whole job
    ;;
  src/dossier/infrastructure/models/*|*/src/dossier/infrastructure/models/*)
    : # left of the boundary -- asking a model is this package's whole job
    ;;
  src/dossier/infrastructure/tracking/*|*/src/dossier/infrastructure/tracking/*)
    : # left of the boundary -- sending records to MLflow is this package's job (R0.19)
    ;;
  src/dossier/infrastructure/index/*|*/src/dossier/infrastructure/index/*)
    : # left of the boundary -- the embedding index is this package's job (R0.19)
    ;;
  src/dossier/*|*/src/dossier/*)
    if printf '%s' "$payload" \
      | grep -qE '(import|from)[[:space:]]+(httpx|requests|aiohttp|urllib3|urllib\.request|http\.client|socket|boto3|atlassian|jira|mlflow|psycopg)([^a-z_]|$)'; then
      echo "BLOCKED: this file is right of the hash boundary (R0.19)." >&2
      echo "Only dossier.infrastructure.connectors, .models, .tracking and .index may reach the network." >&2
      echo "That is what makes a six-month-old run reproducible offline." >&2
      echo "Fix: make the call in a connector and pass the result across." >&2
      exit 2
    fi
    ;;
esac

# 6. The purity boundary. domain/ imports stdlib and pydantic, nothing else.
case "$norm" in
  src/dossier/domain/*.py|*/src/dossier/domain/*.py)
    if printf '%s' "$payload" \
      | grep -qE '(import|from)[[:space:]]+(yaml|typer|mlflow|sqlite3|pathlib|requests|httpx|os|shutil|logging)([^a-z_]|$)'; then
      echo "BLOCKED: domain/ imports the standard library and pydantic, nothing else." >&2
      echo "No IO, no clock, no environment -- it all arrives as an argument." >&2
      echo "That purity is what makes R0.4 and R5.6 testable without a workspace." >&2
      exit 2
    fi
    if printf '%s' "$payload" \
      | grep -qE '(datetime\.now|datetime\.utcnow|time\.time|uuid4|random\.|os\.environ)'; then
      echo "BLOCKED: domain/ must be deterministic." >&2
      echo "R0.4 and R5.6 claim cache keys are byte-identical across machines." >&2
      echo "Take a clock or an id generator as a parameter instead." >&2
      exit 2
    fi
    ;;
esac

exit 0
