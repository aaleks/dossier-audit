#!/usr/bin/env bash
# Stop hook: when the turn ends, say whether spec and code still agree.
#
# Advisory, not blocking -- a Stop hook that fails would strand work. It runs
# the two checks that answer "are we still in line?" and prints the answer, so
# drift is noticed at the end of the turn rather than at the next review.

set -uo pipefail
cd "$(dirname "$0")/../.." || exit 0

# Only worth running when something under those paths actually changed.
# --porcelain rather than `git diff --quiet`, because a brand new spec or test
# file is untracked and a plain diff would not see it -- which is exactly the
# case this hook most needs to catch.
if [ -z "$(git status --porcelain -- src tests docs/specs 2>/dev/null)" ]; then
  exit 0
fi

out=$(uv run pytest tests/architecture -q 2>&1 | tail -5)
if printf '%s' "$out" | grep -q "failed"; then
  echo "SPEC/ARCHITECTURE DRIFT -- run 'uv run pytest tests/architecture' :"
  printf '%s\n' "$out"
else
  echo "spec <-> code alignment: OK"
fi
exit 0
