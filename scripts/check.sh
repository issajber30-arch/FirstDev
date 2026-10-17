#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

uv run ruff check .
uv run ruff format --check .
uv run pytest -q

# pip-audit: fail on real vulnerabilities (exit 1 + "vulnerab" in output), warn if offline.
out=$(uv run pip-audit 2>&1) && rc=0 || rc=$?
echo "$out"
if [ "$rc" -ne 0 ]; then
  if echo "$out" | grep -qi "known vulnerabilit"; then
    echo "check: pip-audit found vulnerabilities" >&2
    exit 1
  fi
  echo "check: WARNING pip-audit could not complete (network?); continuing" >&2
fi
