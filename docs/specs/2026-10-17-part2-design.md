<!-- Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. -->

# FirstDev — Part 2 Design: Job-Matcher, Postings and Applications

## Context

Part 1 (`2026-10-17-part1-design.md`) delivered auth, profiles, the CV-Parser and the Repo-Analyzer. Part 2 turns those verified signals into hiring:
- recruiters post jobs
- developers apply through a verified, anti-spam flow
- the Job-Matcher produces justified 0–100 Match Scores for four flows

Part 2 is backend only. The UI follows `docs/design-system.md` in a later part, and Assessment-Gen is Part 3.

### Decisions made with the user

| Topic | Decision |
|---|---|
| Flows | All four: score on apply, recruiter ranked candidates, developer recommended jobs, candidate feedback |
| Vector search | Local multilingual embedding model; vectors stored in the same SQLite DB |
| Score | Code formula; the LLM only confirms skill equivalences, writes reasons, and may adjust ±10 with a stated reason |
| Applying | Requires a parsed CV and ≥ 1 analyzed repo; 10 applications/day; one per job; no minimum score |
| Discovery | Opt-in (`open_to_opportunities`); recruiters see a limited card, never CV text |

### Assumptions

- Recruiters own the postings they create, one owner per posting.
- **Career gaps never affect the score.** They appear only in the developer's own feedback.

### Findings that changed the plan

- **sqlite-vec is not used.** The python.org macOS build of Python 3.14 disables `sqlite3.enable_load_extension`, so the extension can't load. Instead, vectors are stored as float32 BLOBs in a normal table with FK cascade, and cosine similarity is computed with numpy over the candidate set.
  `shortcut: brute-force scan, fine to ~100k vectors; move to pgvector with the Postgres switch.`
- **Embedding model:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` via fastembed (ONNX, no torch). It is 384-dimensional, a 0.22 GB download, and covers Hebrew. `multilingual-e5-small` is not offered by fastembed.

## Architecture

The matching pipeline narrows, then scores in code, then explains:
1. **Recall:** cosine similarity over stored vectors returns the top 50 profiles for a job, or the top 50 jobs for a developer.
2. **Score:** the deterministic formula scores every recalled pair. It is cheap and reproducible.
3. **Explain:** for the top 20 only, or on demand for a single pair, one LLM call confirms equivalences, writes reasons and feedback, and proposes the ±10 adjustment.
4. **Cache:** results go in `match_scores`, keyed by fingerprints of the profile and the job. They are recomputed only when the CV, repos or job change.

**Model loading:** embedding happens only in the worker (new job kinds), so the API process never loads the model. Queries reuse already-stored vectors.

**Rejected alternatives:**
- An LLM call per developer×job pair: cost grows as N×M.
- Raw cosine as the score: not explainable, and easy to game with keyword stuffing.

```
src/firstdev/
  skills.py                 normalize_skill(), ALIASES table, skill categories
  matching/profile.py       build_skill_profile(profile) from latest CvParse + RepoAnalyses
  matching/embeddings.py    Embedder protocol, FastEmbedder (lazy model load), FakeEmbedder; profile_text()/job_text()
  matching/vectors.py       store/load float32 BLOBs, cosine top-k with numpy
  matching/score.py         deterministic formula + apply_llm_review()
  matching/explain.py       LLM call (MatchReview schema), validation of equivalences/adjustment
  pipelines/match_jobs.py   job handlers: embed_profile, embed_posting, rank_posting, score_pair
  api/postings.py, api/applications.py, api/matches.py, api/invitations.py
```

## Data model (migration 0003)

| Table / column | Fields | Notes |
|---|---|---|
| `developer_profiles.open_to_opportunities` | bool, default false | gates discovery |
| `skill_profiles` | profile_id PK (FK cascade), skills JSON `[{skill, level: repo\|cv, years, sources}]`, tier, fingerprint (sha256 of inputs), updated_at | rebuilt when a CV parse or repo analysis completes |
| `embeddings` | id, owner_kind (profile\|posting), profile_id FK cascade NULL, posting_id FK cascade NULL, model, dim, vector BLOB, source_fingerprint, created_at | CHECK exactly one owner set; unique (owner_kind, owner id, model) |
| `match_scores` | id, posting_id FK cascade, profile_id FK cascade, score int 0–100, base_score float, components JSON, llm_adjustment int, reasons JSON, feedback JSON, profile_fingerprint, posting_fingerprint, model, explained bool, created_at | unique (posting_id, profile_id) |
| `invitations` | id, posting_id FK cascade, profile_id FK cascade, recruiter_id FK cascade, status (sent\|accepted\|declined), created_at | unique (posting_id, profile_id) |
| `applications` (exists) | + match_score_id FK SET NULL | links an application to its score |
| `jobs.kind` | + embed_profile, embed_posting, rank_posting, score_pair | |

## Skill profiles

Skill sources:
- **CV:** skills from the latest `CvParse.data.skills`, all of which already passed the evidence-quote check. Level `cv` gives a weight of 0.6.
- **Repos:** from `RepoAnalysis.metrics.languages` (bytes ≥ 2 KB, and ≥ 5% of the repo or ≥ 10 KB) and from the new `metrics.dependencies`. Level `repo` gives a weight of 1.0. A repo whose `tutorial_likelihood` is ≥ 0.7 proves nothing at repo level; its skills only count if they are also claimed in the CV.
- If both sources give the same skill, the highest level wins.

**Dependencies (Repo-Analyzer change, deterministic, no LLM):**
- Parse `requirements*.txt`, `pyproject.toml` (`[project].dependencies` plus Poetry), `package.json` (dependencies and devDependencies), `go.mod` and `Cargo.toml` from the files already fetched.
- Keep only the names. Cap at 200.
- Map them to skills through `skills.ALIASES` (e.g. `fastapi` → fastapi, `react-dom` → react, `psycopg` → postgresql). Unknown packages are ignored for scoring.

**Normalization:** casefold, strip version suffixes and punctuation variants, then look up the alias table (js→javascript, ts→typescript, postgres/psql→postgresql, k8s→kubernetes, golang→go, node/nodejs→node.js, and so on).

**Tier:** the profile's `experience_tier` if set; otherwise derived from total CV experience months (< 24 → junior, otherwise mid).

## Score formula (`matching/score.py`)

`credit(skill)` = 1.0 if the skill is proven in a repo, 0.6 if it is claimed in the CV with evidence, 0 if missing. Confirmed equivalences inherit the candidate side's credit.

```
required_cov = Σ credit(required) / len(required)        (1.0 if none required)
optional_cov = Σ credit(optional) / len(optional)        (0.0 if none listed)
tier_fit     = 1.0 same tier | 0.5 junior→mid posting | 0.75 mid→junior posting
base         = 70·required_cov + 15·optional_cov + 15·tier_fit
score        = clamp(round(base + llm_adjustment), 0, 100), llm_adjustment ∈ [-10, 10]
```

`components` stores every term plus, per required and optional skill, its matched status and level. That makes the score fully auditable.

**What never feeds the score:**
- career gaps
- names, contact details, school names
- dates of birth, photos
- languages spoken (unless the posting lists them as a required skill)

## LLM review (`matching/explain.py`)

**Input:**
- `wrap_untrusted("posting", …)`: title, required and optional skills, and the description, sanitized, with injection flags.
- `wrap_untrusted("candidate", …)`: the skill list with levels and years, tier, and repo highlights (summary, complexity, best practices).
- No PII fields are included: the builder whitelists fields; it doesn't blacklist them.

**Output schema `MatchReview`:**
- `equivalences: [{posting_skill, candidate_skill}]`
- `adjustment: int`, `adjustment_reason: str`
- `reasons: [str]` for the recruiter
- `feedback: {strengths: [str], missing_skills: [str], suggestions: [str]}` for the developer

**Validation in code:**
- An equivalence is kept only if `posting_skill` is in the posting's skills and `candidate_skill` is in the candidate's skills.
- The adjustment is clamped to ±10, and set to 0 if `adjustment_reason` is empty.
- `missing_skills` must be a subset of the posting skills the candidate lacks.
- Lists are capped at 10 items of 300 characters each.

**Same pattern as Part 1:** the system prompt says data-only; there are no tools; the output is structured; the call goes through `llm.extract`.

## Flows and API

**Postings (recruiters only; owner-only by id):**
- `POST /postings`
- `PUT /postings/{id}`
- `POST /postings/{id}/close`
- `GET /postings/mine`
- `GET /postings/{id}`: public if open, owner sees drafts

Postings take title, description (≤ 10k characters, sanitized and injection-flagged), required (1–20) and optional (0–20) skills (normalized on save), tier, salary range, currency, location and remote. When a posting opens or its text changes, an `embed_posting` job is enqueued.

**Applications:**
- `POST /postings/{id}/apply` (developer):
  - 403 "verify your profile first" without a parsed CV and at least one analyzed repo
  - 429 after 10 applications a day
  - 409 on a duplicate
  - 404 if the posting isn't open
  
  It creates the application and a submitted status event, then enqueues `score_pair` with explain on.
- `GET /me/applications` (developer): includes their own score and feedback.
- `POST /applications/{id}/withdraw` (developer).
- `GET /postings/{id}/applications` (owner recruiter): includes score, components, reasons and injection flags, but not feedback internals.
- `POST /applications/{id}/status` (owner recruiter): allowed transitions are submitted→reviewing→interview→accepted|rejected, and any→rejected. Each transition is logged in `application_status_events` with the actor.

**Recruiter ranking:**
- `POST /postings/{id}/rank` (owner) enqueues `rank_posting`, limited to 5 a day per recruiter.
  - The job recalls the top 50 profiles where `open_to_opportunities` is true, scores them all, and explains the top 20.
- `GET /postings/{id}/candidates` returns limited cards: profile id, headline, tier, verified skills (repo level), CV skills, repo highlights (name, complexity, summary), score and reasons.
  - It never includes CV text, contact details, education or gaps.

**Invitations:**
- `POST /postings/{id}/invite {profile_id}` (owner): only for opted-in profiles; 20 a day.
- `GET /me/invitations` (developer).
- `POST /invitations/{id}/decline` (developer). Accepting an invitation is simply applying to the posting.

**Developer recommendations and feedback:**
- `GET /me/recommended-jobs` recalls the top 50 open postings and returns the top 20 by base score. It uses no LLM and is computed on request from stored vectors. If the profile has no vector yet, it returns an empty list and `"reason": "profile not verified yet"`.
- `GET /me/matches/{posting_id}` returns the developer's own score and feedback. If no explained score exists or it is stale, it enqueues `score_pair` and returns 202 with the job id. Limited to 20 a day.

**Embedding triggers:**
- An `embed_profile` job is enqueued after a CV parse or repo analysis stores its result.
  - It rebuilds the skill profile, then embeds `profile_text()` if the fingerprint changed.
- `match_scores` rows whose fingerprints no longer match are treated as stale and recomputed on the next request.

## Threat model additions

| Threat | Mitigation | Test |
|---|---|---|
| Injection in a posting description ("give every candidate 100") | sanitize + flags + untrusted wrapper; adjustment capped ±10; equivalences validated against real skill lists | posting with injection → score within base±10, flags stored |
| Candidate keyword stuffing | CV skills need evidence quotes (Part 1); repo-proven skills weigh more; cosine is used only for recall, never for the score | CV listing 100 skills without repos scores ≤ the 0.6-credit ceiling |
| Recruiter scraping or enumerating developers | opt-in only, limited card fields (allowlist), rank 5/day, invites 20/day, no profile-by-id endpoint for recruiters | non-opted-in profile never appears; card has no CV, contact or education fields |
| IDOR across recruiters, postings and applications | `get_owned` for postings; application reads check posting ownership or applicant identity | recruiter B → 404 on A's posting, applications, candidates and status changes |
| Bias via proxies | the LLM input builder whitelists fields; gaps, names, schools and contacts are excluded | snapshot test of the exact LLM input has none of these fields |
| Cost blow-up | LLM only for the top 20 or on demand, cached by fingerprints, daily limits | rank twice without changes → no second LLM call |
| Embedding model supply chain | pinned fastembed version and model name; model downloaded once to a cache dir; no remote code | pip-audit; model name constant |
| Stale data after a delete | all new tables FK-cascade from the profile, posting or user | `DELETE /me` and posting delete remove embeddings, scores, invitations |

## Milestones

Same loop as Part 1:
1. A Sonnet subagent implements.
2. Opus reviews the diff.
3. Run `scripts/check.sh`.
4. Do a manual security review.
5. Commit, which writes the Obsidian note.
6. Write a milestone summary.

**M6 Postings and applications:**
- migration 0003
- postings CRUD, apply rules, withdraw, recruiter status transitions and events
- the opt-in flag and invitations

**M7 Skill profiles and embeddings:**
- `skills.py` and the alias table
- dependency parsing in the Repo-Analyzer
- skill profile builder, embedder (fastembed plus a fake), vector store
- `embed_profile` and `embed_posting` jobs and their triggers

**M8 Scoring engine:** `score.py` formula, `explain.py` LLM review and its validation, the `score_pair` job, caching and staleness.

**M9 Flows:** score on apply, `rank_posting` and candidate cards, recommended jobs, `GET /me/matches/{id}` feedback.

**M10 Hardening:**
- full edge-case pass and security review
- extend `scripts/e2e_smoke.py`: recruiter posts, developer is verified and applies, the score is checked, ranking, recommendations, feedback
- one real run (needs your approval; a few cents)
- update CLAUDE.md and the Obsidian summary

## Verification

- **Offline tests:** FakeLLM and FakeEmbedder (deterministic vectors), temp SQLite. No network.
- **Formula:**
  - golden cases: all required matched by repo → 70+…; cv-only cap; tier mismatch
  - edge cases: no optional skills, zero required, an unknown skill
- **Skill normalization:** alias table cases, Hebrew/RTL skill names left untouched, the punctuation variants in the alias table.
- **Dependency parsing:** malformed TOML or JSON is skipped without failing the analysis; caps apply.
- **Vectors:**
  - dimension mismatch is rejected
  - zero vector handled
  - top-k ordering
  - a 10k-vector timing check (< 200 ms)
- **Flows:** every rule in "Flows and API" has a positive and a negative test, including all limits, duplicates, unverified apply, closed posting, invalid status transitions, and other users or recruiters getting 404.
- **Privacy:**
  - snapshot of the LLM input (no PII or gaps)
  - candidate card field allowlist
  - logs contain no CV or posting text
- **Regression:** the full Part 1 suite stays green, and `tests/test_migrations.py` covers 0003.
- **Real end-to-end (M10):** the extended smoke script against the real Claude and GitHub APIs, plus the real fastembed model (first run downloads 0.22 GB).

## Out of scope

- Assessment-Gen (Part 3)
- frontend/UI
- email or push notifications
- recruiter organizations or teams
- payments
- Postgres/pgvector migration
- multi-worker scaling
