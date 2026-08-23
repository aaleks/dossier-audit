#!/usr/bin/env bash
# Stop hook: when the turn ends, say whether spec and code still agree.
#
# Advisory, not blocking -- a Stop hook that fails would strand work. It runs
# the checks that answer "are we still in line?" and prints the answer, so drift
# is noticed at the end of the turn rather than at the next review.

set -uo pipefail
cd "$(dirname "$0")/../.." || exit 0

# Only worth running when something under those paths actually changed.
# --porcelain rather than `git diff --quiet`, because a brand new spec or test
# file is untracked and a plain diff would not see it -- which is exactly the
# case this hook most needs to catch.
if [ -z "$(git status --porcelain -- src tests specs 2>/dev/null)" ]; then
  exit 0
fi

if command -v uv >/dev/null 2>&1; then
  runner="uv run pytest"
elif [ -x ".venv/Scripts/python.exe" ]; then
  runner=".venv/Scripts/python.exe -m pytest"
elif [ -x ".venv/bin/python" ]; then
  runner=".venv/bin/python -m pytest"
else
  runner="python -m pytest"
fi

out=$($runner tests/architecture -q 2>&1 | tail -6)
if printf '%s' "$out" | grep -qE "failed|error"; then
  echo "SPEC/ARCHITECTURE DRIFT -- run '$runner tests/architecture' :"
  printf '%s\n' "$out"
else
  # The summary line the coverage test prints is the useful part: how many rules
  # exist, how many are met, and whether an outer loop is open.
  printf '%s\n' "$out" | grep -E "^specs:" || echo "spec <-> code alignment: OK"
fi
exit 0
