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
```

- Part 1 design: `docs/specs/2026-10-17-part1-design.md`
- Design system: `docs/design-system.md`
