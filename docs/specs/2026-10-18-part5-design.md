<!-- Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. -->

# FirstDev — Part 5 Design: Web frontend

## Context

The backend is complete through Part 4: 961 tests pass, and the real end-to-end runs pass for every part. The user wants to **see and click through the platform**.

Part 5 is the Next.js web app, run locally first; Part 6 deploys it. Decisions come from the roadmap (`2026-10-17-roadmap.md`) and the design system (`docs/design-system.md`). The user asked to plan and execute without another question round, so the defaults below were taken.

## Stack and structure

| Concern | Choice |
|---|---|
| Framework | Next.js, latest stable, App Router, TypeScript `strict`, in `web/` |
| Styling | Tailwind CSS. Tokens from `docs/design-system.md` as CSS variables + Tailwind theme: `bg-base #0B0F19`, `bg-surface #111827`, `accent-primary #00F2FE`, `accent-verified #FFB703`, `text-primary #F8FAFC`; fonts Inter (UI) and JetBrains Mono (code/metrics) via `next/font` |
| i18n | `next-intl`, locales `en` and `he` under `/[locale]/…`; `dir="rtl"` for Hebrew; logical CSS properties only (`ms-`, `me-`, `ps-`, `pe-`, `start`, `end`) |
| Data | client components calling `/api/*` with `fetch` (`credentials: "same-origin"`) through one wrapper `lib/api.ts`; `swr` for reads and polling |
| API types | `openapi-typescript` generates `lib/api-types.ts` from the backend's `/openapi.json` (dev); the wrapper is typed with it |
| Proxy | `app/api/[...path]/route.ts` forwards every method to `FIRSTDEV_API_URL` with `/api` stripped. It passes the body, the `Cookie` header and `X-CSRF-Token`, and returns status, body and every `Set-Cookie`. It adds `X-FirstDev-Proxy-Secret` (server env) and `X-FirstDev-Client-IP` (from the request). The backend runs with `FIRSTDEV_COOKIE_PATH_PREFIX=/api`. Timeout 30 s; body limit 6 MB |
| Auth on the client | `lib/api.ts` echoes the `fd_csrf` cookie as `X-CSRF-Token` on unsafe methods. On a 401 it calls `POST /api/auth/refresh` once and retries; if that fails it routes to sign-in |
| Security | Strict CSP with a per-request nonce (middleware): `default-src 'self'; script-src 'self' 'nonce-…' 'strict-dynamic' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`. No `dangerouslySetInnerHTML`; all user and LLM text is rendered as text. No tokens in `localStorage`. `X-Content-Type-Options`, `Referrer-Policy: strict-origin-when-cross-origin` |
| Turnstile | rendered only when `NEXT_PUBLIC_TURNSTILE_SITE_KEY` is set; otherwise "Try the demo" posts without a token (the backend in dev has Turnstile disabled) |

## Brand

`components/brand/Logo.tsx`, an inline SVG:
- an "FD" monogram whose letters' verticals rise into a stepped skyline
- the tallest towers drawn as `<` and `/>` brackets
- cyan stroke and glow on dark

It also produces the favicon (`app/icon.svg`) and an Open Graph image (`app/opengraph-image.tsx`).

**Visual motifs:**
- a subtle city-grid background (a CSS gradient pattern)
- glass cards: translucent surface, a 1 px border with a faint cyan glow on hover or focus
- amber for verified badges and GitHub metrics
- monospace for scores and metrics

**Motion:**
- short (150–250 ms), only on state changes (score reveal, card hover, step transitions)
- respects `prefers-reduced-motion`

## Screens

**Public:**
- `/` landing: hero, how verification works (CV + repos + assessments), "Try as developer" / "Try as recruiter", sign in
- `/sign-in`
- `/join`: invite registration
- `/u/[handle]`: public profile

**Developer** (`/dev/…`):

| Screen | Contents |
|---|---|
| Dashboard | profile completeness, verified skills (repo / assessment / CV levels with legend), quick links |
| Profile | edit headline, bio, tier, GitHub username, open-to-opportunities, handle + public toggle (hidden in sandboxes) |
| CV | upload a PDF or paste text, job status, parsed skills/experience/education, injection flags shown as warning badges |
| Repos | add a GitHub URL, analysis status, metrics (languages bar, tests/CI/lint, commits), assessment summary, best practices with evidence paths, tutorial likelihood meter |
| Jobs | recommended jobs with score bars, matched and missing skills; match detail with score breakdown (required/optional/tier terms, levels) and feedback incl. own gaps |
| Applications | list, status, withdraw |
| Invitations | list, decline, apply |
| Assessments | list; start; one-question-at-a-time view with a server-synced countdown (`seconds_left` from the API, re-synced on each answer); MCQ radio group; short-answer textarea with a character counter (2000); report with per-skill bars, per-question review and study suggestions |
| Connections | requests in/out, accept/decline/remove |

**Recruiter** (`/rec/…`):

| Screen | Contents |
|---|---|
| Postings | list/create/edit/close with skill chip inputs, tier, salary, remote, auto-assessment toggle (hidden in sandboxes) |
| Applicants | per posting: score, breakdown, reasons, injection flags, status transitions, send assessment, assessment results |
| Candidates | rank button, job status, ranked cards (verified skills amber, CV skills grey, repo highlights, score, reasons, stale badge), invite |

**Sandbox banner:** when `/me` returns a `world_id`, a top banner shows "Demo sandbox — expires in hh:mm" and remaining AI quota hints. A 429 "demo limit" message is shown inline.

**Empty, loading and error states** exist for every list and job, including 403 "verify your profile first" with links to CV and Repos.

## Backend touch-ups (small, in this part)

- `GET /me` returns `world_id` presence as `sandbox: bool` and `expires_at`, so the banner works without exposing the world id. Add these to the existing `UserOut`.
- `FIRSTDEV_COOKIE_PATH_PREFIX=/api` in the frontend dev setup.

## Testing

- **Vitest + Testing Library:** the countdown (sync, expiry, reduced motion), the score breakdown math display, the API wrapper (CSRF echo, single refresh retry, no retry loop), and the RTL layout snapshot of one component.
- **Playwright:**
  - `scripts/web-e2e.sh` starts a fresh API (fake LLM mode, Turnstile disabled, invite required), the worker and `next build && next start`.
  - It then runs flows in both locales:
    - landing → try as developer → explore jobs → match detail → take a practice assessment → report
    - try as recruiter → rank → candidates
    - invite registration → public profile → connection
- **axe:** `@axe-core/playwright` on every main screen; zero serious or critical violations.
- **Lighthouse:** on the landing page (performance, accessibility, best practices ≥ 90), run locally against `next start`.
- **Security checks:**
  - CSP header present with a nonce
  - no inline scripts without the nonce
  - `npm audit --omit=dev` with no high or critical issues
  - a grep gate: no `dangerouslySetInnerHTML` and no `localStorage` token code

## Running locally

`scripts/dev.sh` starts the API (:8000), the worker and Next.js (:3000) with dev env defaults:
- fake or real LLM chosen by a flag
- Turnstile disabled
- the proxy secret generated per run

It prints the URL, and stops all three on Ctrl-C.

## Milestones

- **M19:** scaffold, tokens, fonts, logo, i18n + RTL, proxy route, API wrapper + types, middleware CSP, landing, sign-in, join, demo entry, sandbox banner, `scripts/dev.sh`, the backend `/me` touch-up.
- **M20:** developer screens (dashboard, profile, CV, repos, jobs + match detail, applications, invitations, connections).
- **M21:** assessments UI (list, take with countdown, report) + recruiter screens (postings, applicants, candidates) + public profile.
- **M22:** Playwright flows (en + he), axe, Vitest suite, Lighthouse, security gates, polish pass (`emil-design-eng` guidance), README screenshots; hand over a running local instance for the user to try.

## Out of scope

- deployment (Part 6)
- email
- an admin UI
- native mobile (the layout is responsive down to 360 px)
