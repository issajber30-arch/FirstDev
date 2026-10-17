<!-- Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. -->

# FirstDev Part 4 (Web sessions, demo safety, sandboxes, social) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend safe and usable behind a public Next.js demo:
- cookie sessions with CSRF protection
- invite-only real signups
- a $5/day LLM budget that can't be overshot
- fully isolated 24 h personal sandboxes cloned from a rich pre-computed Israeli tech world
- connections and opt-in public profiles

**Architecture:** the existing API + worker. Five new tables: refresh_tokens, invite_codes, llm_ledger, sandbox_creations, plus connection and user columns. A single `same_world` helper scopes every cross-user query. The budget is enforced centrally inside `AnthropicLLM.extract`. Sandboxes are cloned from `fixtures/demo_world.json`.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 + Alembic, httpx (Turnstile), pytest + respx + FakeLLM.

**Spec:** `docs/specs/2026-10-17-part4-design.md`. Every table, limit and route there is binding.

## Global Constraints

- `CLAUDE.md` rules apply: copyright headers; Sonnet implements, Opus reviews per milestone.
- Existing tests keep passing. They use Bearer auth, and conftest sets `FIRSTDEV_REQUIRE_INVITE=false`, `FIRSTDEV_TURNSTILE_DISABLED=true` and `FIRSTDEV_COOKIE_SECURE=false`.
- No network in tests. Turnstile goes through respx and the LLM through FakeLLM or CannedLLM.
- Secrets are compared with `hmac.compare_digest`. Tokens and codes are stored only as sha256 hashes. Raw IPs are never stored.
- Logs carry ids and counts only.
- Limits:

  | What | Limit |
  |---|---|
  | Access cookie | 15 min |
  | Refresh token | 7 days, rotating |
  | Sandboxes | 3 per IP per 24 h |
  | Sandbox lifetime | 24 h |
  | Sandbox quota | cv_parse 1, repo_analyze 1, assessment 1, score_pair-explain 4, rank_posting 2 (explaining the top 5) |
  | Connections | 50/day; 30-day decline cooldown |
  | Public profile reads | 60/min per IP |
  | LLM budget | `FIRSTDEV_LLM_DAILY_USD` default 5.0 |
  | Prices (Opus 5.5) | $4 in / $20 out per MTok |

## Review Focus

1. **An access cookie expires mid-session while a write is in flight.** Expected: 401 with `WWW-Authenticate`, so the frontend can call `/auth/refresh` and retry once. Refresh must work even though the access cookie has expired. Test in Task 1.
2. **Two concurrent `/auth/refresh` calls with the same token**, e.g. two browser tabs. Expected: exactly one succeeds; the second counts as reuse and revokes the family, and both tabs end up logged out. This is a known and accepted trade-off, documented in the code. Test in Task 1.
3. **The budget is nearly exhausted and a large CV parse arrives.** Expected: the reservation is refused **before** the API call, the job fails with "demo AI budget reached for today", and the sandbox quota isn't consumed. Test in Task 3.
4. **The sweep runs while a sandbox job is mid-flight.** Expected: the handler's owner or object is gone, so it no-ops; no FK errors; the ledger row is released or kept with world_id nulled. Test in Task 6.
5. **A sandbox visitor guesses real ids** (posting, profile or connection ids taken from the public profile or the URL). Expected: 404 everywhere. Covered by the world-leak suite in Task 4.

---

## M15: Sessions, proxy trust, headers, invites

### Task 1: Cookie sessions, refresh rotation, CSRF, logout

**Files:**
- Create: `src/firstdev/sessions.py`, `tests/test_sessions.py`
- Modify: `models.py` (RefreshToken), `auth.py` (`current_user` cookie support), `api/auth.py` (login sets cookies; refresh; logout), `app.py` (CSRF middleware), `config.py` (`cookie_secure`)
- Migration `0005_web.py`, shared with Tasks 2–6. Generate it once at the end of M15 and amend it within Part 4 (it isn't committed until M15).

**Interfaces:**
- `issue_session(db, response, user) -> str`: new family; sets the three cookies; returns the access token
- `rotate(db, response, raw_refresh) -> User`: raises 401 on invalid, expired or revoked tokens; on reuse it revokes the family and raises 401
- `revoke_family(db, family_id)`
- `clear_cookies(response)`
- `CSRFMiddleware`: a pure ASGI middleware, like `BodySizeLimit`. A request is "cookie-authenticated" when there is no `Authorization` header and `fd_access` is present.

- [ ] **Step 1: Write the failing tests:**
  - login sets the three cookies with exact flags (httpOnly, SameSite, Path, Secure per setting)
  - `GET /me` with only the cookie → 200
  - a cookie POST without `X-CSRF-Token` → 403; with a wrong token → 403; with a matching one → passes
  - Bearer POST without CSRF → passes
  - refresh rotates: the old token is used and a new cookie is set
  - **reuse:** refreshing the old token again → 401, and the new token is also dead (family revoked)
  - an expired refresh → 401
  - logout → 204, cookies cleared, refresh dead
  - **Review Focus 1:** an expired access cookie with a valid refresh → refresh succeeds
  - **Review Focus 2:** two sequential refreshes with the same raw token → the second gets 401 and the family is revoked
  - `DELETE /me` clears cookies
  - refresh token rows store only the sha256
- [ ] **Step 2: Run, implement, run. Step 3:** full suite.

### Task 2: Client IP, security headers, invite codes, display_name

**Files:**
- Create: `src/firstdev/security/headers.py`, `src/firstdev/invites.py`, `scripts/invites.py`, `tests/test_invites.py`, `tests/test_headers.py`
- Modify: `auth.py` (`client_ip`, used by `limiter_keys`), `api/auth.py` (register: `invite_code`, `display_name`), `models.py` (InviteCode; `User.display_name`), `config.py` (`proxy_secret: SecretStr | None`, `require_invite`, `cookie_secure`)

**Rules:**
- **`client_ip`:** as the spec says. In prod, `proxy_secret` is required (startup validation when `env == "prod"`).
- **Headers middleware:** the spec's list. `Cache-Control: no-store` is added when the request carried credentials.
- **Invite alphabet:** `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (31 symbols; no I, O, 0 or 1), 12 characters, generated with `secrets.choice`, printed as `XXXX-XXXX-XXXX`, and normalized (uppercase, dashes removed) before hashing.
- **Register:**
  - `display_name` is required: 1–60 characters after `sanitize_text`.
  - With `require_invite` on, the code must exist, be unused and not revoked. It is marked used in the same transaction as user creation.
  - The 403 message is identical for unknown, used and revoked codes, and each bad attempt counts on the IP limiter.

- [ ] **Step 1: Write the failing tests:**
  - a spoofed `X-FirstDev-Client-IP` without the secret is ignored; with the secret it's honoured
  - each header is present; HSTS only in prod
  - CLI create, list and revoke run via subprocess against a temp DB, and `list` never prints codes
  - register with a valid code → 201 and the code is used; reuse → 403; revoked → 403; unknown → 403 (all bodies equal)
  - the 6th bad code from one IP → 429
  - lowercase or no-dash input is accepted
  - missing `display_name` → 422; 61 characters → 422; Hebrew is accepted
- [ ] **Step 2: Run, implement, run.**
- [ ] **Step 3: M15 gate (Opus):** review, security pass, generate and clean migration 0005 (all M15 tables and columns), commit `M15: cookie sessions, CSRF, invites, headers`, Obsidian note.

---

## M16: Budget ledger and fake mode

### Task 3: LLM ledger, BudgetExceeded, context, CannedLLM

**Files:**
- Create: `src/firstdev/budget.py`, `src/firstdev/canned_llm.py`, `tests/test_budget.py`, `tests/test_canned_llm.py`
- Modify:
  - `llm.py`: `PRICES`, `extract(..., *, context: LLMContext | None = None)`, reservation around the call
  - pipelines: `cv_parser`, `repo_analyzer`, `matching/explain`, `assessments/generate`, `assessments/grade`, which pass `LLMContext(user_id, world_id, kind)` from the job
  - `config.py`: `llm_mode: Literal["real", "fake"] = "real"`, `llm_daily_usd: float = 5.0`
  - `models.py`: LlmLedger
  - migration: a new `0006_budget.py` (0005 is committed by then)

**Interfaces:**
- `LLMContext(user_id: str | None, world_id: str | None, kind: str)`
- `budget.reserve(db_factory, ctx, worst_usd) -> str`: returns the ledger id or raises `BudgetExceeded`. It uses its **own** session and commits immediately, so the reservation is visible to concurrent workers and survives handler rollback.
- `budget.settle(db_factory, ledger_id, usage)`, `budget.release(db_factory, ledger_id)`
- `BudgetExceeded(LLMPermanentError)` with the message "demo AI budget reached for today"
- `estimate_worst_usd(system, content, max_tokens) -> float`
- `CannedLLM.extract(schema, system, user_content, ...)` dispatches on the schema type and returns a deterministic valid instance, built from the input text so Part 1–3 validators pass. For example, CV quotes are the first lines of the CV.
- `get_llm()` returns CannedLLM when `llm_mode == "fake"`. App startup raises if `llm_mode == "fake"` and `env == "prod"`.

- [ ] **Step 1: Write the failing tests:**
  - reserve under budget → row reserved; settle sets actual and settled; release on an exception
  - **Review Focus 3:** at the cap minus a little, a big reservation → `BudgetExceeded` before any client call (the fake client records no calls), and the job fails with the message
  - the sum uses actual when settled, else reserved
  - day rollover (UTC) resets the total
  - **concurrency:** 10 threads each reserving 0.6 against a cap of 5 → exactly 8 succeed (SQLite with `BEGIN IMMEDIATE` inside reserve; document it)
  - every pipeline passes context: the FakeLLM records `context.kind` for cv_parse, repo_analyze, score_pair, assessment_generate and assessment_grade
  - CannedLLM output passes `validate_extraction`, `validate_assessment`, `validate_review`, `validate_generated` and `apply_grades` on representative inputs
  - fake mode in prod → startup error
  - CannedLLM writes no ledger rows
- [ ] **Step 2: Run, implement, run. Step 3:** full suite.
- [ ] **Step 4: M16 gate (Opus):** review (budget math and race), commit `M16: LLM budget ledger and fake mode`, Obsidian note.

---

## M17: Worlds, public profiles, connections, Hebrew aliases

### Task 4: Worlds and the world-leak suite

**Files:**
- Create: `src/firstdev/worlds.py`, `tests/test_world_isolation.py`
- Modify: `models.py` (`User.world_id`, `User.expires_at`); every cross-user query in `api/postings.py` (`GET /postings/{id}`, `load_open_posting`), `api/applications.py`, `api/invitations.py`, `api/matches.py`, `pipelines/match_jobs.py` (ranking pool, recommendations), `api/assessments.py` (recruiter send); migration 0007.

**Interfaces:**
- `same_world(stmt, user_col, caller: User)`: adds `user_col.world_id IS NULL` or `== caller.world_id` via a join to User
- `in_world(db, user_id, caller) -> bool`

- [ ] **Step 1: Write the failing world-leak suite.**
  - Fixture: build worlds R (real), A and B, each with a recruiter, an open posting, 2 verified opted-in developers, an application, an invitation and a match score.
  - For each world's developer and recruiter, call: `GET /postings/{other-world id}` → 404; apply to another world's posting → 404; invite another world's developer → 404; rank → candidates only from its own world; recommended jobs → only its own world's postings; `GET /me/matches/{other posting}` → 404; recruiter send assessment for another world's application → 404.
  - Assert no foreign uuid appears in any JSON body (regex over the response text against the foreign ids).
  - **Review Focus 5** is covered here.
- [ ] **Step 2: Run, implement, run.**

### Task 5: Handles, public profiles, connections, Hebrew aliases

**Files:**
- Create: `src/firstdev/api/public.py`, `src/firstdev/api/connections.py`, `tests/test_public_profiles.py`, `tests/test_connections.py`
- Modify: `models.py` (`User.handle`, `User.public_profile`; `Connection.responded_at`, the `ConnectionStatus.removed` enum value), `api/profiles.py`, `skills.py` (aliases + tests in `tests/test_skills.py`); migration 0007 (shared with Task 4)

**Rules:** the spec's sections 8, 9 and 10.
- The public profile limiter is a `FailureLimiter`-style counter keyed by `client_ip`, counting every request rather than failures. Add a `RateLimiter` class next to `FailureLimiter` (`hit(key) -> bool`).
- `verified_at` for repo-level skills is the latest `RepoAnalysis.created_at` among the repos that contributed the skill. That requires `build_skill_profile` sources (already stored as `owner/name` strings), or recompute from analyses.

- [ ] **Step 1: Write the failing tests:**
  - handle regex: valid; too short; leading or trailing `-`; uppercase → normalized to lowercase; reserved words → 422; duplicate → 409
  - `public_profile` refused for recruiters and sandbox users (422)
  - `GET /u/{handle}`:
    - private profile → 404
    - sandbox user → 404, with a body identical to an unknown handle
    - public → exact key set; badges include repo and assessment but not CV-only skills; an expired assessment badge is excluded
    - the 61st request in a minute from one IP → 429
    - `Cache-Control` header present
  - connections:
    - request → pending; accept; decline; remove
    - self → 422; duplicate in either direction → 409
    - decline then re-request within 30 days → 409 (generic); after 30 days → allowed (time injected)
    - another world → 404; a third party accepting → 404
    - 51st in a day → 429
    - the list shows display_name, handle and headline only
  - Hebrew aliases: each entry in the spec maps correctly, and both geresh forms work
- [ ] **Step 2: Run, implement, run.**
- [ ] **Step 3: M17 gate (Opus):** review, security pass (isolation is critical), commit `M17: worlds, public profiles, connections`, Obsidian note.

---

## M18: Sandboxes

### Task 6: Turnstile, IP limit, demo world fixture, clone, quotas, sweep

**Files:**
- Create: `src/firstdev/demo/__init__.py`, `src/firstdev/demo/turnstile.py`, `src/firstdev/demo/clone.py`, `src/firstdev/demo/quota.py`, `src/firstdev/api/demo.py`, `fixtures/demo_world.json`, `tests/test_sandbox.py`
- Modify: `jobs.py` (sweep in `worker_main`), every quota-relevant route (`POST /profiles/me/cv`, `POST /profiles/me/repos`, apply / matches (score_pair explain), rank, `POST /me/assessments`, recruiter send) to call `quota.check(db, user, kind)` when `user.world_id` is set; postings (force `auto_assessment=false` in sandboxes); `config.py` (`turnstile_secret`, `turnstile_disabled`); models (SandboxCreation); migration 0008.

**`fixtures/demo_world.json`** (the copyright notice goes in a top-level `"_copyright"` key, because JSON has no comments) contains, all hand-written and realistic:

| Content | Detail |
|---|---|
| Recruiter | "Noa Levi — Talent Lead, Helix Labs (Tel Aviv)" |
| Postings (4, open) | Junior Backend (Python/FastAPI/PostgreSQL), Junior Frontend (React/TypeScript), Mid Full-stack (Node.js/React/Docker), Junior Data (Python/pandas/SQL) |
| Developers (6) | headline, tier, CV text (2 in Hebrew with English tech terms), CvParse data (evidence quotes present in the CV text), 1–2 repos with RepoAnalysis metrics (languages, dependencies) and assessment |
| Developer profiles | **Strong repo-proven** · **CV-only claims** · **Tutorial-heavy** (`tutorial_likelihood` 0.85) · **Assessment badge holder** (graded assessment + badge for React) · **Career changer** (gap in CV) · **Mid-level Node dev** |
| Match fixtures | reasons and feedback text per (developer, posting) for the developer clone and the top candidates |
| Visitor templates | the developer visitor clones the "Strong repo-proven" persona as "You (Demo Developer)"; the recruiter visitor becomes "You (Demo Recruiter)" owning the 4 postings |

**Clone rules:** the spec's section 7.
- Fingerprints are computed after the skill profiles are built. Match scores are inserted with `score_and_store(explain=False)` and then given the fixture reasons, feedback and `explained=True` and `model="demo-fixture"`.
- Embedding jobs are enqueued.
- One transaction; rollback on any error.

- [ ] **Step 1: Write the failing tests:**
  - Turnstile (respx): success → 201 with cookies set; failure → 403; disabled in dev OK; disabled + prod → startup error
  - 4th sandbox from one IP in 24 h → 429; a different IP → OK; the table stores only hashes
  - clone:
    - creates the full world (counts per table)
    - all persona passwords are unusable (login fails)
    - the visitor user's `world_id` and `expires_at` are set
    - match scores are present and not stale
    - two sandboxes are fully disjoint (no shared ids)
    - a fixture validation test: every evidence_quote is in its CV text, every repo evidence path is in its files list, and the skills normalize
  - quotas: a 2nd CV parse in a sandbox → 429; a 2nd assessment (practice or recruiter-sent) → 429; the 5th explain → 429; the 3rd rank → 429; rank in a sandbox explains only the top 5 (FakeLLM call count); real users are unaffected
  - sandbox postings can't enable `auto_assessment`
  - sweep:
    - expired worlds are deleted completely (every table count back to the baseline)
    - ledger rows survive with world_id nulled
    - **Review Focus 4:** a queued job for a swept world → handler no-op, job done or failed without crash
  - sandbox `DELETE /me` deletes the whole world
- [ ] **Step 2: Run, implement, run. Step 3:** full suite + `scripts/check.sh`.

### Task 7: The `--part4` end-to-end flow and docs

**Files:** modify `scripts/e2e_smoke.py`, `tests/test_e2e_smoke_gates.py`, `CLAUDE.md`, `README.md` (invites CLI, demo env vars).

`--part4 --fake` (free; runs with `FIRSTDEV_LLM_MODE=fake` and `FIRSTDEV_TURNSTILE_DISABLED=true` in the child env):
1. Create a developer sandbox; cookies work for `GET /me`; CSRF is enforced on a POST.
2. The world is visible: recommended jobs list the 4 postings; matches show the fixture feedback.
3. Run one CV parse, one repo analysis (GitHub still real; or skip with `--no-github`) and one practice assessment end to end.
4. The second CV parse gets 429.
5. Create a recruiter sandbox: its candidates come only from its own world; the developer sandbox's ids never appear.
6. Public profile: a real invite-registered developer with a public profile is visible at `/u/{handle}`; a sandbox handle → 404.
7. Connections between two invite users work; a sandbox → real-user request → 404.
8. Refresh rotation works over HTTP, and reuse is rejected.

`--part4` without `--fake` runs the same flow with real Claude. Additionally, the ledger total for the day equals the sum of settled rows, and the reported cost is printed.

- [ ] **Step 1: Implement. Gate tests:** `--part4` without `--yes` → exit 2. `--fake` doesn't need `ANTHROPIC_API_KEY`, but still needs `--yes`, because it starts servers and calls GitHub.
- [ ] **Step 2:** `scripts/check.sh`; run `--part4 --fake --yes` (free), then report.
- [ ] **Step 3: Real run.** Ask the user first: `--part4 --yes`.
- [ ] **Step 4: M18 gate (Opus):** final security review against the spec's threat table, commit `M18: sandboxes and Part 4 E2E`, Obsidian Part 4 summary.
