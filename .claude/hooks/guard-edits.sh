#!/usr/bin/env bash
# PreToolUse: refuse edits that break the project's two hard rules.
#
# Exit 2 blocks the tool call and returns stderr to Claude as feedback.
# Exit 0 allows it. Anything else is a hook error, not a block.
#
# Kept deliberately small. Rules needing real parsing belong in the test suite
# where they can be debugged; a hook is for the two mistakes that are cheap to
# detect now and expensive to discover later.

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
  *.env|*/.env)
    echo "BLOCKED: $norm holds live credentials." >&2
    echo "Edit it yourself and tell me what changed." >&2
    exit 2
    ;;
esac

# 2. Golden eval data is a human decision.
#    The failure mode of eval-driven work is "the eval failed, so adjust the expected
#    answer". That silently lowers the bar and leaves the suite green. Prepare the
#    cases, show them, let a human write the file.
case "$norm" in
  */tests/evals/golden/*|tests/evals/golden/*)
    echo "BLOCKED: golden eval data is changed by a human, not by an agent." >&2
    echo "Editing expected answers until an eval passes is how a threshold dies." >&2
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

# 4. The domain layer imports nothing. import-linter catches this in the suite,
#    but catching it at write time saves a red run and explains the reason.
#
#    Grep the raw JSON payload: written content arrives as a JSON string with
#    newlines escaped, so an import statement still appears verbatim. An
#    earlier version tried to unescape it first and silently matched nothing,
#    which is worse than no hook.
case "$norm" in
  src/playground/domain/*.py|*/src/playground/domain/*.py)
    if printf '%s' "$payload" \
      | grep -qE '(import|from)[[:space:]]+(mlflow|langfuse|litellm|langchain[a-z_]*)([^a-z_]|$)'; then
      echo "BLOCKED: domain/ imports nothing -- no LangChain, no MLflow, no Langfuse." >&2
      echo "That purity is what makes these rules testable without a server." >&2
      echo "Put the SDK call in infrastructure/ and pass the decision in." >&2
      exit 2
    fi
    ;;
esac

exit 0
