<!-- Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. -->

# FirstDev — Part 4 Design: Web sessions, demo safety, sandboxes, connections, public profiles

## Context

Parts 1–3 built the backend for scripts and tests: Bearer tokens that last 15 minutes, open registration, and no cost controls.

The roadmap (`2026-10-17-roadmap.md`) sets the goal as a **public portfolio demo on GCP Cloud Run with a Next.js frontend**. That needs four things:
- browser sessions
- protection against cost abuse
- instant personal demo sandboxes, isolated from real users
- the light social layer: connections and public profiles

## Decisions made with the user

| # | Topic | Decision |
|---|---|---|
| 1 | Browser ↔ API | **The Next.js server proxies `/api/*`.** Cookies are first-party on the frontend origin and no CORS is needed |
| 2 | Demo | **Personal sandbox:** "Try as developer/recruiter" clones a pre-built world for that visitor only |
| 3 | AI in sandboxes | **Real Claude with a small quota,** under the global budget |
| 4 | Budget | **$5/day** for the whole deployment |
| 5 | Bots | **Cloudflare Turnstile + 3 sandboxes per IP per day** |
| 6 | Real signups | **Personal single-use invite codes** (CLI-generated, revocable) |
| 7 | Session | **15-minute access cookie + 7-day rotating refresh;** reuse revokes the session family |
| 8 | Connections | **Anyone to anyone;** 50 requests/day; a declined pair can't be re-requested for 30 days |
| 9 | Isolation | **Fully isolated worlds:** sandboxes never see real users or other sandboxes, and vice versa |
| 10 | Budget accuracy | **Reserve worst-case cost before each LLM call,** settle after; it never overshoots |
| 11 | Public profile | **Verified skill badges only** (repo or assessment), plus handle, display name, headline, tier |
| 12 | Seed world | **Rich Israeli tech scene:** 1 recruiter (Tel Aviv startup), 4 postings, 6 developers, mixed English/Hebrew, all pre-computed |
| 13 | Sandbox quota | **1 CV parse + 1 repo analysis + 1 assessment,** plus up to 4 match explanations |
| 14 | Model | **Opus 5.5 everywhere** |
| 15 | Sandbox lifetime | **24 h after creation,** deleted by a worker sweep |

## 1. Sessions

**Cookies** are set by the API, and reach the browser through the Next.js proxy on the same origin:

| Cookie | Content | Flags |
|---|---|---|
| `fd_access` | HS256 JWT (existing claims), 15 min | httpOnly, Secure*, SameSite=Lax, Path=/ |
| `fd_refresh` | 32 random bytes (urlsafe), opaque | httpOnly, Secure*, SameSite=Strict, Path=/api/auth |
| `fd_csrf` | 32 random bytes | **not** httpOnly (the frontend reads it), Secure*, SameSite=Strict, Path=/ |

\* Secure is set when `FIRSTDEV_COOKIE_SECURE` is true (default true; false only when `env=dev`, for http://localhost).

**`refresh_tokens` table:** id, user_id FK cascade, family_id, token_hash (sha256, unique), expires_at, used_at, revoked_at, created_at.

**Routes:**
- `POST /auth/login`: on success sets all three cookies and still returns `access_token`, so scripts keep working. It creates a new family.
- `POST /auth/refresh` (cookie only):
  - Valid and unused: mark it used, issue a new token in the same family with expires = now + 7 d, and reset the access and CSRF cookies.
  - **Already used: revoke the whole family** (theft signal) → 401.
  - Expired or revoked → 401.
- `POST /auth/logout`: revokes the family and clears the cookies (204).

**Authentication:** `current_user` accepts an `Authorization: Bearer` header **or** the `fd_access` cookie, Bearer first.

**CSRF:**
- Any unsafe method (POST/PUT/PATCH/DELETE) authenticated **by cookie** must send `X-CSRF-Token` equal to the `fd_csrf` cookie, compared with `hmac.compare_digest`. Otherwise → 403.
- Bearer-authenticated requests are exempt (no ambient credentials).
- Login, refresh and sandbox creation are exempt: login has no session yet, refresh is SameSite=Strict with a narrow path, and sandbox creation is protected by Turnstile.

**`DELETE /me` and logout** clear the cookies.

## 2. Client IP behind the proxy

`client_ip(request)` returns `X-FirstDev-Client-IP` **only** when `X-FirstDev-Proxy-Secret` matches `FIRSTDEV_PROXY_SECRET` (`hmac.compare_digest`; setting required in prod). Otherwise it returns `request.client.host`.

Every per-IP limit uses it: login, sandbox creation and public profiles. The Next.js proxy (Part 5) sets both headers. Cloud Run's own `X-Forwarded-For` is not trusted directly.

## 3. Security headers (API middleware)

These apply to every response:
- `Strict-Transport-Security: max-age=31536000` (prod only)
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (the API serves JSON only)
- `Cache-Control: no-store` on authenticated responses

## 4. Invite codes (real accounts)

**`invite_codes` table:** id, code_hash (sha256, unique), label, created_at, used_at, used_by FK users SET NULL, revoked_at.

**`scripts/invites.py`:**
- `create --label "Dana (Wix)"` prints the code **once**: 12 characters from an unambiguous alphabet, grouped as `XXXX-XXXX-XXXX`.
- `list` shows label and status, never codes.
- `revoke --label|--id`.

**`POST /auth/register`** gains `invite_code` and `display_name`, and requires an unused, unrevoked code when `FIRSTDEV_REQUIRE_INVITE` is true (default true; tests may set false). It marks the code used in the same transaction.
- An invalid code → 403 "invalid invite code", with the same message for unknown, used and revoked codes.
- Attempts count toward the per-IP failure limiter.

## 5. LLM budget ledger and fake mode

**`llm_ledger` table:** id, day (UTC date), user_id FK SET NULL, world_id NULL, kind, reserved_usd, actual_usd NULL, status (reserved | settled | released), created_at.

**Pricing constants:** Opus 5.5 is $4 / $20 per MTok input / output, kept in one place (`llm.PRICES`).

**Reserve (inside `AnthropicLLM.extract`):**
1. Worst case = (`count_tokens`-free estimate: `len(system + content) / 3` input tokens) × input price + `max_tokens` × output price.
2. In one transaction, if `Σ(actual_usd or reserved_usd for today, status != released) + worst > FIRSTDEV_LLM_DAILY_USD`, raise `BudgetExceeded`, a permanent error with the message "demo AI budget reached for today".
3. Otherwise insert a reserved row.

**Settle:** after the call, set actual = usage × prices, status settled. If the call raised, status released.

**Context:** `extract` takes keyword-only context (`user_id`, `world_id`, `kind`). The pipelines pass it from the job.

**Fake mode:** `FIRSTDEV_LLM_MODE=fake` makes `get_llm()` return `CannedLLM`, which builds a deterministic, schema-valid instance for each output schema the app uses:
- CVExtraction: quotes taken from the input text, so the evidence checks pass
- RepoAssessment: evidence paths taken from the input
- MatchReview
- GeneratedAssessment: on-target skills, valid rubrics
- GradeResult

`fake` with `env=prod` → startup error. CannedLLM writes no ledger rows.

## 6. Worlds (isolation)

**`users.world_id`:** str(36) NULL, indexed. Real users are NULL. Each sandbox has its own uuid world shared by its visitor and its persona users.

**`users.expires_at`:** NULL for real users, created_at + 24 h for sandbox users.

**The rule:** any query that returns or matches **another user's** data filters by the caller's world (`world_id IS NULL` for real users, `= :w` for sandboxes). A single helper does it: `worlds.same_world(stmt, user_column, caller)`. It covers:
- the ranking pool and candidate cards
- recommended jobs, apply, `load_open_posting`, `GET /postings/{id}`
- invitations (the target must be in the same world)
- connections
- the application lists (already ownership-scoped; the world check is added as defence in depth)
- public profiles (**real world only**)

Owner-scoped routes (`get_owned`) are already safe.

**Test strategy:** a parametrized **world-leak suite**. It creates a real world and two sandbox worlds with matching data, calls every cross-user route as each world's user, and asserts that no foreign id appears in any response body.

## 7. Sandboxes

`POST /demo/sandbox {role: "developer" | "recruiter", turnstile_token}` (no auth):
1. **Turnstile:** server-side `POST https://challenges.cloudflare.com/turnstile/v0/siteverify` (fixed URL, 5 s timeout) with `FIRSTDEV_TURNSTILE_SECRET`, the token and `client_ip`. Failure → 403. `FIRSTDEV_TURNSTILE_DISABLED=true` is allowed only when `env != prod`.
2. **Per-IP limit:** 3 sandboxes per `client_ip` per 24 h → 429. The count lives in a `sandbox_creations` table (ip_hash = sha256(ip + JWT secret), created_at), so the limit works across instances and raw IPs are never stored.
3. **Clone** `fixtures/demo_world.json` into a new world:
   - users with unusable password hashes, `display_name`, `expires_at`
   - profiles, CV documents and parses (text only), repositories and analyses, postings, skill profiles
   - pre-computed match scores (model `demo-fixture`, `explained=true`, fingerprints computed at clone time)
   - one graded assessment with a badge for one persona
   
   Then enqueue `embed_profile` and `embed_posting` jobs (local model, free).
   - The visitor gets their own user in that world: a developer persona clone ("You — Demo Developer") or the recruiter.
4. Set the session cookies for the visitor (as in login) and return 201 `{role, world_id, expires_at}`.

**Sandbox quota.** Per sandbox world, counted from `jobs` by kind across the world's users:

| Kind | Limit |
|---|---|
| cv_parse | 1 |
| repo_analyze | 1 |
| any assessment (practice or recruiter-sent; generate + grade) | 1. Auto-assessment is forced off on sandbox postings |
| score_pair with explain | 4 |
| rank_posting | 2, with explain limited to the top 5 instead of 20 in sandboxes |

Over the limit → 429 "demo limit reached for this sandbox". The global budget still applies on top.

**Sandbox users can't:**
- create invite codes or change their email or password
- connect outside their world
- make their profile public

`DELETE /me` works and deletes the whole world.

**Sweep:** a worker task every 10 minutes deletes users with `expires_at < now` (cascades remove everything), then deletes the world's leftover rows (ledger keeps aggregate rows with world_id set to NULL). It runs inside `worker_main` next to `requeue_stale`.

## 8. Profiles: display name, handle, public page

**New `users` fields:**
- `display_name` (1–60, sanitized, required at register)
- `handle` (unique, `^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$`, reserved words blocked: admin, api, demo, u, me, login, …)
- `public_profile` (bool, default false; developers only; real world only)

`PUT /profiles/me` handles them. Handle conflict → 409.

**`GET /u/{handle}`** (no auth, 60/min per IP, `Cache-Control: public, max-age=60`):
- Returned only when `public_profile` is true **and** world is NULL. Otherwise 404, with the same body as unknown.
- Body (allowlist): `{handle, display_name, headline, tier, verified_badges: [{skill, source: "repo"|"assessment", verified_at}]}`.
  - Repo-level skills give `verified_at` = the latest analysis date.
  - Assessment badges count only if unexpired.

## 9. Connections

**`connections` (exists)** gains `responded_at` and the status `removed`.

**Routes:**
- `POST /connections {user_id}`:
  - same world; not self; the target exists
  - 50/day → 429
  - an existing pending or accepted pair (either direction) → 409
  - a pair declined within 30 days (either direction) → 409 with a generic message, so the requester doesn't learn they were declined
- `POST /connections/{id}/accept` and `/decline` (addressee only)
- `DELETE /connections/{id}` (either party; status removed)
- `GET /me/connections`: accepted, with the other party's `{user_id, display_name, handle, headline}`
- `GET /me/connection-requests`: incoming and outgoing pending

Everyone else gets 404.

## 10. Hebrew tech aliases

`skills.ALIASES` gains exact-key entries:

| Hebrew | Skill |
|---|---|
| פייתון | python |
| ג׳אווהסקריפט / ג'אווהסקריפט | javascript |
| טייפסקריפט | typescript |
| ריאקט | react |
| נוד / נוד.ג׳ייאס | node.js |
| ג׳אווה | java |
| דוקר | docker |
| קוברנטיס | kubernetes |
| פוסטגרס | postgresql |
| מונגו | mongodb |
| גיט | git |
| לינוקס | linux |
| אנגולר | angular |
| וויו | vue |
| ג׳נגו | django |
| פלאסק | flask |
| סי שארפ | c# |
| סי פלוס פלוס | c++ |

Both geresh forms (׳ and ') are covered.

## Threat model additions

| Threat | Mitigation | Test |
|---|---|---|
| Session theft via XSS | httpOnly cookies; no tokens in JS; strict CSP (frontend) | cookie flags asserted |
| CSRF | double-submit header on cookie-authenticated unsafe methods; SameSite | cookie POST without header → 403; with a wrong header → 403; Bearer exempt |
| Refresh token theft | rotation + reuse detection revokes the family; stored hashed | reuse → 401 and the sibling token is dead |
| Cost abuse via sandboxes | Turnstile, 3/IP/day (hashed), per-sandbox quotas, global $5/day reservation ledger | the 4th sandbox → 429; quota → 429; the budget refuses before calling |
| Budget race | reservation inside a transaction; SQLite single-writer (Postgres row lock in Part 6) | concurrent reservations never exceed the cap (threaded test) |
| IP spoofing | client IP header trusted only with the proxy secret | a spoofed header without the secret is ignored |
| Cross-world leak | `same_world` everywhere + world-leak suite | no foreign id in any response |
| Invite brute force | 12 characters from a 31-symbol alphabet (~59 bits); per-IP failure limiter; hashed storage | the 6th bad code → 429 |
| Public profile enumeration and scraping | opt-in, real world only, 404 for hidden, 60/min/IP, allowlist | sandbox and private handles → 404 |
| Connection harassment | 50/day, 30-day decline cooldown with a generic 409 | covered |
| Fake mode in prod | startup refusal | test |
| Sandbox data left behind | 24 h sweep with cascades | sweep test removes everything |

## Milestones

Same loop as before (Sonnet implements; Opus reviews, checks, security pass, commit, Obsidian note).

| Milestone | Scope |
|---|---|
| **M15** | sessions (cookies, refresh rotation, logout, CSRF), client IP behind the proxy, security headers, invite codes + CLI, `display_name` at register |
| **M16** | LLM ledger + `BudgetExceeded`, context passing from pipelines, CannedLLM fake mode, prod guard |
| **M17** | worlds (`world_id`, `same_world` on every cross-user route, world-leak suite), handles + public profiles, connections, Hebrew aliases |
| **M18** | sandboxes: Turnstile, IP limit, `fixtures/demo_world.json` (rich Israeli world), clone, quotas, sweep; extend `e2e_smoke.py --part4` (fake-mode run + one real run on approval) |

## Verification

- **Offline tests:** everything above, including the world-leak suite, the threaded budget test, and refresh reuse.
- **Regression:** the whole suite (689+) stays green. Existing tests keep using Bearer and set `FIRSTDEV_REQUIRE_INVITE=false` in conftest.
- **End-to-end:**
  - Fake mode, free: create a sandbox (Turnstile disabled in dev), explore the world, run the quota-limited AI features, and hit every limit.
  - Real run, on approval: one sandbox with real Claude, checking the ledger settles to the real cost.

## Out of scope

- email
- password reset
- OAuth login
- admin UI
- a feed or messaging
- the frontend itself (Part 5)
- Postgres and deploy (Part 6)
