#!/usr/bin/env bash
# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
# Fresh isolated stack (API :8100, worker, production Next.js :3100, temp SQLite DB), then Playwright.
# Usage: scripts/web-e2e.sh [--lighthouse] [playwright args...]   Exits with Playwright's code.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

lighthouse=0
if [ "${1:-}" = "--lighthouse" ]; then lighthouse=1; shift; fi

tmp=$(mktemp -d)
proxy_secret=$(openssl rand -hex 32)
export FIRSTDEV_ENV=dev
export FIRSTDEV_JWT_SECRET=$(openssl rand -hex 32)
export FIRSTDEV_DATABASE_URL="sqlite:///$tmp/e2e.db"
export FIRSTDEV_LLM_MODE=fake
export FIRSTDEV_TURNSTILE_DISABLED=true
export FIRSTDEV_REQUIRE_INVITE=true
export FIRSTDEV_COOKIE_SECURE=false
export FIRSTDEV_COOKIE_PATH_PREFIX=/api
export FIRSTDEV_PROXY_SECRET="$proxy_secret"

set -m  # one process group per service so a single kill reaches its children
pids=()
cleanup() {
  trap - INT TERM EXIT
  for p in "${pids[@]:-}"; do [ -n "$p" ] && kill -- "-$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$tmp"
}
trap cleanup INT TERM EXIT

for port in 3100 8100; do
  if lsof -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then echo "web-e2e: port $port is busy" >&2; exit 1; fi
done

uv run alembic upgrade head
uv run uvicorn firstdev.app:app --port 8100 >"$tmp/api.log" 2>&1 & pids+=($!)
uv run python -m firstdev.worker >"$tmp/worker.log" 2>&1 & pids+=($!)
(cd web && npm run build >"$tmp/build.log" 2>&1) || { tail -40 "$tmp/build.log" >&2; exit 1; }
(cd web && FIRSTDEV_API_URL=http://localhost:8100 npx next start -p 3100 >"$tmp/web.log" 2>&1) & pids+=($!)

wait_for() {
  for _ in $(seq 1 90); do curl -fsS -o /dev/null "$1" 2>/dev/null && return 0; sleep 1; done
  echo "web-e2e: $1 did not become ready" >&2; tail -20 "$tmp"/*.log >&2; return 1
}
wait_for http://localhost:8100/health || wait_for http://localhost:8100/openapi.json
wait_for http://localhost:3100/en

rc=0
(cd web && BASE_URL=http://localhost:3100 npx playwright test "$@") || rc=$?
if [ "$rc" -eq 0 ] && [ "$lighthouse" -eq 1 ]; then
  scripts/lighthouse.sh http://localhost:3100/en || rc=$?
fi
exit "$rc"
