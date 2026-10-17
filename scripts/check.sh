#!/usr/bin/env bash
# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
set -euo pipefail
cd "$(dirname "$0")/.."

# Every source/config/doc file must carry the copyright notice (JSON and lock files can't).
missing=$({ git ls-files; git ls-files --others --exclude-standard; } | sort -u |
  grep -E '\.(py|sh|toml|ini|md|mako|js|ts|tsx|css|html)$|^\.githooks/|^\.gitignore$|^\.env\.example$' |
  while read -r f; do [ -s "$f" ] && ! grep -q "Copyright (c) 2026 Issa Jber" "$f" && echo "$f"; done || true)
if [ -n "$missing" ]; then
  echo "check: missing copyright header in:" >&2; echo "$missing" >&2; exit 1
fi

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
