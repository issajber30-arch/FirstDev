#!/usr/bin/env bash
# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
# Local dev stack: API :8000, worker, Next.js :3000. Ctrl-C stops all three.
# Usage: scripts/dev.sh [--real]   (--real uses the real LLM; needs ANTHROPIC_API_KEY)
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

mode=fake
[ "${1:-}" = "--real" ] && mode=real

# Fresh shared secret per run: only the Next.js proxy may name the client IP to the API.
proxy_secret=$(openssl rand -hex 32)
export FIRSTDEV_ENV=dev
export FIRSTDEV_JWT_SECRET="${FIRSTDEV_JWT_SECRET:-$(openssl rand -hex 32)}"
export FIRSTDEV_DATABASE_URL="sqlite:///./dev.db"
export FIRSTDEV_COOKIE_PATH_PREFIX=/api
export FIRSTDEV_COOKIE_SECURE=false
export FIRSTDEV_TURNSTILE_DISABLED=true
# Local: every visitor is 127.0.0.1 and X-Forwarded-For is untrusted (no proxy in front).
export FIRSTDEV_SANDBOX_PER_IP_PER_DAY=100
export FIRSTDEV_TRUSTED_PROXY_HOPS=0
export FIRSTDEV_LLM_MODE="$mode"
export FIRSTDEV_PROXY_SECRET="$proxy_secret"

uv run alembic upgrade head

set -m  # job control: each service gets its own process group, so one kill reaches its children
pids=()
cleanup() {
  trap - INT TERM EXIT
  for p in "${pids[@]}"; do kill -- "-$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

uv run uvicorn firstdev.app:app --port 8000 & pids+=($!)
uv run python -m firstdev.worker & pids+=($!)
(cd web && FIRSTDEV_API_URL=http://localhost:8000 FIRSTDEV_PROXY_SECRET="$proxy_secret" npm run dev) & pids+=($!)

echo
echo "FirstDev (LLM: $mode) -> http://localhost:3000"
echo "Ctrl-C to stop."
wait
