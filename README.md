<!-- Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. -->

# FirstDev

A professional network and application platform for junior and mid-level developers. FirstDev checks real coding ability by analysing a developer's GitHub repositories alongside their CV.

**Author:** Issa Jber. Copyright (c) 2026 Issa Jber. All rights reserved. Proprietary software.

## Development

```sh
uv sync                                   # install dependencies
cp .env.example .env                      # then set FIRSTDEV_JWT_SECRET (>= 32 chars)
uv run alembic upgrade head               # create the SQLite database
uv run uvicorn firstdev.app:app --reload  # run the API
scripts/check.sh                          # headers, lint, format, tests, dependency audit
uv run python scripts/e2e_smoke.py --yes    # real Claude + GitHub, costs a few cents
uv run python scripts/e2e_smoke.py --yes --part4 --fake   # Part 4 flow, free
uv run python scripts/invites.py create --label "Dana"    # signup invite code, shown once
```

- Part 1 design: `docs/specs/2026-10-17-part1-design.md`
- Design system: `docs/design-system.md`

## Demo and deployment settings

Environment variables (prefix `FIRSTDEV_`):

- `LLM_DAILY_USD` — global daily cap on real Claude spend (default 5.0); calls are refused once it would be exceeded.
- `LLM_MODE` — `real` (default) or `fake` (canned outputs, free; refused when `ENV=prod`).
- `TURNSTILE_SECRET` — Cloudflare Turnstile secret for `POST /demo/sandbox`; `TURNSTILE_DISABLED=true` skips it (dev/tests only, refused in prod).
- `PROXY_SECRET` — shared with the Next.js proxy; only requests carrying it may name the client IP (required in prod).
- `COOKIE_PATH_PREFIX` — `/api` behind the Next.js proxy, empty when the API is reached directly.
- `REQUIRE_INVITE` — signup needs an invite code (default true); create codes with `scripts/invites.py`.
