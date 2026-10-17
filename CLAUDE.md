# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# FirstDev

Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. Author: Issa Jber.

## Commands

- `uv sync` — install dependencies (Python 3.12+, uv)
- `scripts/check.sh` — copyright-header check, ruff check, ruff format --check, pytest, pip-audit
- `uv run pytest tests/test_cv_api.py::test_text_cv_end_to_end` — run a single test
- `uv run alembic upgrade head` — create/upgrade the SQLite DB (`FIRSTDEV_DATABASE_URL`)
- `uv run alembic revision --autogenerate -m "..." --rev-id 000N` — new migration; then replace any `firstdev.models.UTCDateTime` with `sa.DateTime(timezone=True)`. `tests/test_migrations.py` fails if models and migrations drift.
- `uv run uvicorn firstdev.app:app --reload` — API; `uv run python -m firstdev.worker` — background worker (needed for CV/repo jobs)
- `uv run python scripts/e2e_smoke.py --yes [--part2|--part3]` — real Claude + GitHub end-to-end (needs `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`; costs money — ask first)
- `uv run python scripts/e2e_smoke.py --yes --part4 --fake` — Part 4 only (sandboxes, cookies/CSRF, invites, public profiles, connections, refresh); `--fake` uses `CannedLLM`, free, no `ANTHROPIC_API_KEY`. Without `--fake` it uses real Claude and also checks the budget ledger (costs money — ask first)
- `uv run python scripts/invites.py create --label NAME | list | revoke` — signup invite codes (code shown once)

- `scripts/dev.sh [--real]` — API + worker + web on http://localhost:3000 (fake AI unless `--real`)
- `scripts/web-e2e.sh [--lighthouse]` — Playwright (dev screens, assessments/recruiter, a11y, security) against an isolated production build on :3100/:8100
- Web: `npm --prefix web run lint`, `npx --prefix web tsc --noEmit -p web`, `npm --prefix web test -- --run`. Read `web/AGENTS.md` first: this Next.js version has breaking changes.

Git hooks live in `.githooks` (`core.hooksPath`): pre-commit scans staged content for secrets, blocks `.env` and runs ruff; post-commit writes an Obsidian note. `FIRSTDEV_JWT_SECRET` (≥32 chars) is required; tests set it in `tests/conftest.py`.

## Architecture

Spec: `docs/specs/2026-10-17-part1-design.md`. Part 1 = backend, schemas, CV-Parser, Repo-Analyzer. Part 2 = postings, applications, Job-Matcher. Part 3 = assessments (spec `docs/specs/2026-10-17-part3-design.md`). The frontend comes later.

- **Two processes, one SQLite DB.** The FastAPI API (`app.py`, routers in `api/`) writes a `jobs` row and returns 202. The worker (`worker.py` → `jobs.worker_main`) claims jobs atomically (`UPDATE … RETURNING`, single worker only) and dispatches by `JobKind` through `jobs.HANDLERS`. Pipelines register their handler (and optional `FAILURE_HOOKS` entry) at import, and `worker.py` imports them. Retries happen only for `errors.TransientError` subclasses, with backoff via `jobs.run_after`, max 3 attempts. `last_error` only ever holds firstdev's own messages.
- **Pipelines** (`pipelines/cv_parser.py`, `pipelines/repo_analyzer.py`) share one pattern: sanitize (`security/sanitize.py`) → heuristic `injection.scan` flags (stored, never blocking) → `wrap_untrusted(...)` delimiters → `llm.extract(schema, SYSTEM_PROMPT, content)` (structured output, no tools) → post-validation in code (evidence quotes/paths must exist in the source, clamps, caps). Deterministic facts (CV gaps, repo metrics, tutorial heuristics) are computed in code, never by the LLM.
- **LLM** (`llm.py`): `AnthropicLLM` uses `client.beta.messages.parse` with `fallbacks="default"`, model `FIRSTDEV_LLM_MODEL` (default `claude-opus-5-5`). It logs only ids and token counts. Tests use `FakeLLM` and override `get_llm()`; GitHub is overridden the same way via `get_github()` (with respx for client tests). No test makes a real network call.
- **Security invariants:**
  - CV uploads are typed by magic bytes, never by filename. PDFs are parsed in an isolated subprocess (`security/_pdf_worker.py`), and the raw file is never stored. `BodySizeLimit` middleware caps request bodies.
  - The GitHub client only calls `https://api.github.com`, with no redirects and escaped path segments. Repo code is never cloned or run.
  - Every by-id read goes through `auth.get_owned`, which returns 404 for both missing and foreign rows.
  - Job payloads carry ids only, never user content.
  - **Worlds:** real users have `world_id` NULL, and each demo sandbox has its own world. Any query that returns or matches *another* user's data must go through `worlds.same_world` (or `in_world`), and anything outside the caller's world is a plain 404. `tests/test_world_isolation.py` must cover every new cross-user route.
  - **Sessions:** browsers use httpOnly cookies (`fd_access`, `fd_refresh`, `fd_csrf`), and every cookie-authenticated write needs `X-CSRF-Token`. Bearer stays for scripts and tests. `FIRSTDEV_COOKIE_PATH_PREFIX=/api` behind the Next.js proxy.
  - **Client IP behind the proxy:** the Next.js proxy forwards an IP only from the entry appended by a trusted front end (`FIRSTDEV_TRUSTED_PROXY_HOPS`, 0 locally, so it is ignored). Never trust the first `X-Forwarded-For` entry, which the client controls.
  - **LLM budget:** every real Claude call reserves its worst-case cost in `llm_ledger` (`budget.py`) and is refused before the call once `FIRSTDEV_LLM_DAILY_USD` would be exceeded. `FIRSTDEV_LLM_MODE=fake` uses `CannedLLM` (refused in prod).
- **Matching (Part 2, spec `docs/specs/2026-10-17-part2-design.md`).** Recall → score → explain:
  - `matching/profile.build_skill_profile` merges CV skills (`cv`, 0.6 credit) with repo evidence (`repo`, 1.0). Repo evidence comes from languages ≥ 2 KB and manifest dependencies. Repos with `tutorial_likelihood` ≥ 0.7 prove nothing.
  - `matching/vectors.top_k` does numpy cosine recall over float32 BLOBs in `embeddings`.
  - `matching/score.base_score` is the deterministic 70/15/15 formula.
  - `matching/explain` is the only LLM step: it confirms equivalences, writes reasons and feedback, and adjusts ±10 only with a reason. Its input is built from an allowlist, never from CV dumps.
  - `match_scores` are cached and treated as stale when the skill-profile or posting fingerprint changes.
  - The embedding model (fastembed `paraphrase-multilingual-MiniLM-L12-v2`, cached in `~/.cache/firstdev/models`) loads only in the worker. Tests use the autouse `FakeEmbedder` fixture.
  - Privacy rules: recruiter-facing outputs (candidate cards, application lists) are explicit allowlist models with no CV text, contacts, education, gaps or feedback. Gaps appear only on the developer's own `GET /me/matches/{id}`.
- **Assessments (Part 3).** Created by a recruiter (`POST /applications/{id}/assessment`), automatically on apply (posting `auto_assessment`) or as developer practice (verified profile only, 3/day, 7-day per-skill cooldown). Lifecycle: `generating` (worker job, one LLM call) → `ready` → `in_progress` (20-minute deadline, finalized lazily on access) → `submitted` → `graded` (`failed`/`expired` otherwise). Answer keys (`correct_index`, rubric, explanation, model answer) live only in `assessment_questions`; candidate and recruiter responses are allowlist models, and the developer report appears only once graded. Grading is code: MCQs are compared in `grade.py`, short answers get a rubric-based LLM verdict that is validated and clamped in code, and no route calls the LLM in-request. A skill scoring ≥ 70% writes a `skill_badges` row with source `assessment`, which `build_skill_profile` merges at level `assessment` (repo > assessment > cv).
- **DB:** SQLAlchemy 2 models in `models.py`, all user-owned rows cascade from `users`, so `DELETE /me` wipes everything. Datetimes use `UTCDateTime` (always aware UTC). Enums are non-native with CHECK constraints.

## Development protocol (applies to every task)

1. **Models:** planning, architecture, edge cases and threat modeling on Opus 5.5 (`claude-opus-5-5`). Code writing, scripts, test runs and CLI work on Sonnet 5.5 (`claude-sonnet-5-5`): delegate to subagents with `model: "sonnet"`, following the approved plan exactly.
2. **Skills/agents:** use the skills and agents already installed instead of rebuilding their workflows.
3. **Plan first:** no code before a written plan is approved.
4. **Security at every stage:** check for injection (XSS, SQL, shell), prompt injection in any LLM-facing input, input sanitization, and API keys or secrets in code.
5. **Testing after every implementation:** E2E on the real flow, regression on existing features, then edge cases (empty, missing, very long, invalid, boundary). Report actual results, failures included.
6. **Code quality:** clean, commented code. Finish every module; no placeholders left behind.
7. **Progress log:** when a milestone or task is done, save a structured progress/state summary to Obsidian (folder set by `FIRSTDEV_OBSIDIAN_LOG_DIR` in `.env`, via `scripts/obsidian_log.py`).
8. **Copyright header:** every source and doc file starts with the notice in that file type's comment syntax: `# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.` (Python, shell, TOML, INI), `/* ... */` (JS/TS/CSS), `<!-- ... -->` (Markdown/HTML). Not possible in JSON or generated lock files. Package metadata author is `Issa Jber`.
9. **Design system:** all UI work follows `docs/design-system.md` (dark-first urban/terminal theme, palette tokens, Inter/Geist + JetBrains Mono).
