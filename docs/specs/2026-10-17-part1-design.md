<!-- Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. -->

# FirstDev — Part 1 Technical Architecture Plan

## Context

FirstDev is a LinkedIn-style network for junior and mid-level developers. It checks a developer's real ability by combining their CV with analysis of their GitHub repos. Part 1 builds the foundation everything else depends on:
- the backend
- the data schemas
- the CV-Parser pipeline
- the Repo-Analyzer pipeline
- the security threat model

Job-Matcher, Assessment-Gen, the frontend and the brand/logo come in later parts.

the project folder is empty: just CLAUDE.md, no git, no code. Nothing exists to reuse.

**Decisions made with the user:**
- Stack: Python + FastAPI.
- Database: SQLite through SQLAlchemy and Alembic, so moving to Postgres later is a config change.
- Obsidian log location: the Obsidian vault folder set by `FIRSTDEV_OBSIDIAN_LOG_DIR`.

**Environment:**
- Python 3.14.7 and uv are installed.
- No Docker, Homebrew or Postgres.

**What CV-Parser, Repo-Analyzer, Job-Matcher and Assessment-Gen are:** they are not installed Claude Code skills. In FirstDev they are the product's own backend pipeline modules, and Part 1 builds the first two.

## Architecture

**Approach:** a modular monolith. It is one FastAPI API process plus one worker process, both sharing a SQLite database. CV parsing and repo analysis are slow (they call the LLM and GitHub), so they run in the background:
1. The API stores a row in the `jobs` table and returns `202` with a job id.
2. The worker picks up the row, runs the pipeline, and writes the result.
3. The client polls `GET /jobs/{id}` for status.

There is no Redis and no Celery. The job queue is a DB table that a single worker claims with `UPDATE … RETURNING`.
`shortcut: single worker only; upgrade to Postgres SKIP LOCKED when we need >1 worker.`

**LLM:** the Claude API through the official `anthropic` Python SDK.
- Default model is `claude-opus-5-5`, configurable with `FIRSTDEV_LLM_MODEL`. Switching to `claude-sonnet-5-5` would roughly halve cost per call.
- Outputs are validated with structured outputs (`client.messages.parse` + Pydantic models).
- Refusals trigger an automatic retry on another model (server-side fallback, `fallbacks: "default"`).
- The prompt is checked for `refusal` and `max_tokens` stop reasons.
- The pipelines give the model no tools, so injected text in a CV or repo can at worst skew a field. It can never trigger an action.

```
src/firstdev/
  app.py, config.py (pydantic-settings, .env), db.py, models.py (SQLAlchemy), schemas/ (Pydantic I/O + CVData, RepoAssessment)
  auth.py (argon2 + short-lived JWT), api/ (auth, profiles, cv, repos, jobs routers)
  jobs.py (enqueue/claim/worker loop, stuck-job requeue), llm.py (one extract() wrapper; FakeLLM for tests)
  security/ sanitize.py, injection.py, uploads.py
  github.py (REST client, fixed base URL), pipelines/cv_parser.py, pipelines/repo_analyzer.py
migrations/ (Alembic)   tests/ unit|integration|fixtures   scripts/ check.sh, obsidian_log.py, e2e_smoke.py
.githooks/ pre-commit (secret scan + ruff), post-commit (Obsidian log)
docs/specs/2026-10-17-part1-design.md (this plan, copied at M0, incl. brand notes for later parts)
```

**Dependencies:**
- Runtime: fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy, alembic, argon2-cffi, pyjwt, python-multipart, pypdf, httpx, anthropic.
- Dev: pytest, respx, ruff (with bandit `S` rules), pip-audit.

## Data schemas (Alembic migration 0001)

| Table | Key fields | Notes |
|---|---|---|
| users | id (uuid), email (unique, lowercased), password_hash, role (developer/recruiter/admin) | |
| developer_profiles | user_id PK, headline, bio, location, experience_tier (junior/mid), github_username | |
| connections | requester_id, addressee_id, status (pending/accepted/declined) | unique pair; requester ≠ addressee |
| skill_badges | profile_id, skill, level, source (cv/repo/assessment), evidence JSON | schema only; filled in Part 2/3 |
| cv_documents | profile_id, sha256, size, page_count, status, extracted_text, injection_flags JSON | **raw file deleted after text extraction** (data minimization) |
| cv_parses | cv_document_id, schema_version, model, data JSON (CVData) | |
| repositories | profile_id, owner, name, is_fork, stars, pushed_at | unique (profile, owner, name) |
| repo_analyses | repository_id, commit_sha, metrics JSON, assessment JSON, tutorial_likelihood, model | |
| job_postings | recruiter_id, title, description, required_skills, optional_skills, tier, salary_min/max, currency, location, remote, status | schema + validation only; endpoints in Part 2 |
| applications / application_status_events | job_posting_id, profile_id, status; from→to, actor, timestamp | unique (job, profile); schema only |
| jobs | kind (cv_parse/repo_analyze), payload, status, attempts, last_error, locked_at | queue |

## Part 1 API

- `POST /auth/register`, `POST /auth/login`, `GET /me`, `DELETE /me` (deletes all of the user's data)
- `GET|PUT /profiles/me`
- `POST /profiles/me/cv` (file upload or pasted text) → 202; `GET /cv/{id}`; `DELETE /cv/{id}`
- `POST /profiles/me/repos {url}` → 202; `GET /repos/{id}/analysis`
- `GET /jobs/{id}`
- Users can only read their own CVs, repos and jobs. Someone else's id returns 404, which also hides that the record exists (blocks IDOR).

## CV-Parser pipeline

1. **Upload checks** (`security/uploads.py`):
   - PDF ≤ 5 MB with the `%PDF-` file signature, ≤ 10 pages, not encrypted.
   - Or text ≤ 200 KB.
   - The browser's content type and the filename are ignored. The filename is never used as a path.
2. **Text extraction:** pypdf runs in a subprocess with a 20 s timeout and a cap on output size, which guards against PDF bombs and parser hangs. Extraction runs synchronously in the upload request, so the raw file is never written to disk or the DB (only sanitized text is stored). A PDF with no extractable text is rejected with 422 "no extractable text; scanned PDFs aren't supported yet" and nothing is stored. OCR comes later.
   `shortcut: macOS ignores RLIMIT_AS, so memory is bounded only by timeout; add a container memory limit at deploy.`
3. **Sanitize** (`security/sanitize.py`):
   - Unicode NFKC normalization.
   - Strip control characters, zero-width characters, and bidi override/isolate characters (U+202A–202E, U+2066–2069).
   - Keep the RLM/LRM marks so Hebrew text survives.
   - Cap at 60k characters, with an explicit error instead of silent truncation.
4. **Injection flags** (`security/injection.py`): pattern checks for things like "ignore previous instructions", "system prompt" or "you are now", and for very small or hidden text markers. Matches are **stored as flags** for recruiter review later. They don't block the upload.
5. **LLM extraction:**
   - Fixed system prompt. The CV text goes inside `<untrusted_cv>…</untrusted_cv>`, and the system prompt says that content is data only.
   - The output must match `CVData`: skills[{name, category, years?, evidence_quote}], experience[{title, company, start, end, evidence_quote}], education[].
6. **Post-validation:**
   - Every `evidence_quote` must appear in the sanitized source text. Items whose quote doesn't are dropped and flagged, which catches invented content.
   - Date sanity checks.
   - **Gaps between jobs are computed in code from the dates**, not by the LLM.

## Repo-Analyzer pipeline

1. **URL check:** must match `^https://github\.com/<owner 1-39>/<repo 1-100>/?$`. The client only ever calls the fixed `https://api.github.com` base URL, so user input can't point the server at internal addresses (no SSRF).
2. **Fetch via REST** using a server-side, read-only, public-only `GITHUB_TOKEN`:
   - Fetch: metadata, languages, the last 100 commits, and the recursive file tree.
   - **Never clone, run, or install anything from a repo.**
   - Handle 404/private repos, empty repos, a truncated tree, and rate limits (403/429 with the reset time).
3. **File selection:**
   - At most 40 files, each ≤ 100 KB, 400 KB total.
   - Priority: README, manifests, CI config, tests, source entry points.
   - Skip binaries, vendored code, `node_modules`, lockfiles and minified files.
4. **Metrics computed in code:**
   - Languages, file and line counts, whether tests/CI/lint config exist.
   - Commit count, active days, history span, number of authors.
   - Tutorial signals: forks, names like tutorial/course/todo-app, and the whole history landing in one bulk commit.
5. **LLM assessment:**
   - The selected files go in as `<untrusted_file path=…>` blocks. The output must match `RepoAssessment`: architecture_summary, complexity 1–5, best_practices[{practice, observed, evidence_path}], tutorial_likelihood 0–1 with reasons, strengths, concerns.
   - Every `evidence_path` must be one of the files that were fetched, or it is dropped and flagged.
   - The final tutorial likelihood combines the code signals and the LLM's judgment.

## Threat model (STRIDE-lite)

| Threat | Mitigation | Test |
|---|---|---|
| Prompt injection in a CV, repo file, or (Part 2) job description | untrusted tags + data-only system prompt; no tools; schema-only output; evidence must exist in the source; flags stored | fixtures with injection text → output still matches the schema, no invented items, flag set |
| Malicious PDF (bomb, JS, hangs the parser, encrypted) | file-signature/size/page checks, subprocess with timeout, text-only extraction, raw file deleted | generated bomb, encrypted, truncated, non-PDF-renamed-.pdf fixtures |
| SSRF through the repo URL | strict regex + fixed API base URL | `http://localhost`, `github.com.evil.com`, `file://`, `..` paths rejected |
| IDOR on CV/repo/job ids | ownership check in one shared dependency | user B can't read user A's resources (404) |
| Leaked API keys | `.env` git-ignored, `.env.example` only; pre-commit scan for `sk-ant-`, `ghp_`, `github_pat_`; keys never logged | hook test with a fake key |
| PII in logs | log ids, request_id and token counts only; never CV text | log-capture test |
| Account attacks | argon2 hashing, 15-min JWT, login rate limit (per-IP limit kept in memory), uniform error messages | brute-force and enumeration tests |
| Stored XSS (later UI) | API returns raw JSON; the frontend part must HTML-escape. Noted for Part 2 | — |
| Cost / DoS from huge inputs | size caps everywhere, per-user upload quota (e.g. 10 CVs/day), job retries capped at 3 | very long input tests |
| Vulnerable dependencies | `pip-audit` in `scripts/check.sh` | runs every milestone |

## Milestones (Opus plans and reviews; Sonnet subagents implement)

Each milestone runs this loop:
1. A Sonnet subagent implements it (`model: "sonnet"`).
2. Opus reviews the diff.
3. Run `scripts/check.sh`: ruff, pytest, pip-audit, secret scan.
4. Run `/security-review`.
5. Commit, which writes an Obsidian note through the post-commit hook.
6. Opus writes a milestone summary note in Obsidian.

**Milestones:**
- **M0 Scaffold:**
  - git init, uv project, ruff/pytest config, `.gitignore`, `.env.example`, a health endpoint.
  - Install the hooks (`git config core.hooksPath .githooks`) and `scripts/obsidian_log.py`. The vault path lives in `.env` and isn't committed.
  - Copy this plan to `docs/specs/`.
- **M1 Data and auth:** models, migration 0001, auth, profile endpoints, ownership dependency, `DELETE /me`.
- **M2 Shared core:** the sanitize, injection and upload modules, the `llm.extract()` wrapper with FakeLLM, and the job queue and worker (including requeueing stuck jobs).
- **M3 CV-Parser:** the pipeline, endpoints and fixtures, including Hebrew/RTL CVs.
- **M4 Repo-Analyzer:** the GitHub client, the pipeline, endpoints, and mocked GitHub responses with respx.
- **M5 Hardening:**
  - Run the full edge-case list and a final security review.
  - Run the real end-to-end check. **It needs your ANTHROPIC_API_KEY and GITHUB_TOKEN in `.env` and costs a few cents, so I'll ask first.**
  - Refresh CLAUDE.md with the real commands and architecture.
  - Write the Part 1 summary to Obsidian.

## Verification

- **Regression:** `uv run pytest` runs the full suite (unit + integration with a temporary SQLite DB, FakeLLM and respx) every milestone and before every commit.
- **Edge cases, by stage:**
  - Upload: empty file, 0-byte PDF, 5 MB + 1 byte, 11 pages, encrypted, image-only, non-PDF with a .pdf name.
  - Text: empty, 60k + 1 characters, Hebrew/RTL, emoji, bidi tricks, injection text.
  - Repo: empty repo, fork, private/404 repo, truncated tree, binary-only repo, rate-limited (429), malformed and SSRF-style URLs.
  - Queue: worker crash mid-job leads to a requeue; the 3-retry cap.
  - Auth: duplicate email, wrong password, expired JWT, cross-user access.
- **End-to-end:** `scripts/e2e_smoke.py` starts uvicorn and the worker and runs: register → upload a fixture CV → poll → check `CVData` → add a known public repo → poll → check `RepoAssessment`. It calls the real Claude and GitHub APIs.
- **Security:** ruff `S` rules, pip-audit, secret scan, and `/security-review` at every milestone.

## Out of scope for Part 1

Job-Matcher/vector DB, Assessment-Gen, job posting and application endpoints, frontend/brand/logo (the brand notes are saved in the spec), OCR, private repos, multiple workers/Postgres, and deployment.

## Brand and design system (for later parts)

See `docs/design-system.md` (palette, typography, motifs, logo concept).
