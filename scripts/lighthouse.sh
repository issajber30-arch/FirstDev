#!/usr/bin/env bash
# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
# Lighthouse on a running stack. Usage: scripts/lighthouse.sh [URL]  (default http://localhost:3100/en)
# Fails if performance, accessibility or best-practices is below 0.9.
set -euo pipefail
cd "$(dirname "$0")/../web"
export PATH="$HOME/.local/bin:$PATH"
url="${1:-http://localhost:3100/en}"
chrome=$(node -e "console.log(require('@playwright/test').chromium.executablePath())")
out=$(mktemp)
trap 'rm -f "$out"' EXIT
CHROME_PATH="$chrome" node node_modules/lighthouse/cli/index.js "$url" \
  --only-categories=performance,accessibility,best-practices \
  --chrome-flags="--headless=new --no-sandbox" --output=json --output-path="$out" --quiet
node -e '
const r = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
let bad = false;
for (const [k, c] of Object.entries(r.categories)) {
  console.log(`lighthouse ${k}: ${c.score}`);
  if (c.score < 0.9) bad = true;
}
process.exit(bad ? 1 : 0);
' "$out"
