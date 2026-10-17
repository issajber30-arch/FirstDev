<!-- Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. -->

# FirstDev — Part 3 Design: Assessment-Gen

## Context

Parts 1–2 verify developers from CVs and repos and match them to jobs. Part 3 adds **Assessment-Gen**:
- live technical screening questions aimed at a candidate's skill gaps
- grading
- detailed feedback reports
- verified skill badges that feed back into matching

It is backend only. The UI comes in a later part and follows `docs/design-system.md`.

### Decisions made with the user

| Topic | Decision |
|---|---|
| Triggers | Recruiter sends one for an application; automatic on apply; developer self-practice |
| Format | Multiple choice (graded in code) + short written answers (graded by Claude against a rubric). Candidate code is never executed |
| Results | ≥ 70% on a skill → verified badge for 12 months, with full credit in matching (like repo-proven); recruiters see scores; candidates get a report; the match formula's weights are unchanged |
| Integrity | Fresh questions per candidate, 20-minute server-side limit, one question at a time, answers never reach the client before grading, one attempt, badges expire after 12 months |

### Assumptions

- Automatic assessment is a per-posting switch (`auto_assessment`, default off), so the recruiter controls the cost.
- Practice assessments are private. Only the badges they earn are visible, through matching.

## Lifecycle

`generating` → `ready` → `in_progress` → `submitted` → `graded`

Other states:
- `failed`: generation or grading failed permanently.
- `expired`: a `ready` assessment wasn't started within 7 days.

| Step | Who / where | Rules |
|---|---|---|
| Create | API (recruiter send, apply with auto on, or practice) | Enqueue `assessment_generate`; status `generating` |
| Generate | worker, one LLM call | Validated in code (below); store questions with their answer keys server-side; status `ready` |
| Start | `POST /assessments/{id}/start` (candidate) | Only from `ready`; sets `started_at`, and `deadline = started_at + 20 min` (server time) |
| Answer | `GET /assessments/{id}/current`, then `POST /assessments/{id}/answers {question_id, choice_index \| text}` | Strict order (must answer the current question); no going back; rejected after the deadline; short answers ≤ 2000 chars |
| Submit | `POST /assessments/{id}/submit`, or the last answer, or any access after the deadline | Idempotent; unanswered questions score 0; MCQ graded now in code; enqueue `assessment_grade` if there are short answers, else finalize |
| Grade | worker, one LLM call for all short answers | Points per rubric criterion clamped to that criterion's max; must list the criteria met |
| Finalize | code | Per-skill % = earned / possible; ≥ 70% → upsert badge (expires in 12 months); rebuild the skill profile, so match scores go stale and are recomputed when next needed |

## Question generation

Target skills:
- **Recruiter / automatic:** the posting's required skills, then optional ones, where the candidate's skill profile level is missing or `cv`. Up to 3 skills. If there are no gaps, use the required skills (verify claimed strengths).
- **Practice:** 1–3 skills the developer chooses, normalized.

LLM input:
- `wrap_untrusted("assessment_context", …)`: the target skills, the candidate tier, and the posting title plus the sanitized description's first 1500 characters (when there is a posting).
- No CV text and no PII.

LLM output, `GeneratedAssessment`:

```
questions: [
  {kind: "mcq",   skill, difficulty: 1..3, prompt, options: [4 strings], correct_index, explanation}
  {kind: "short", skill, difficulty, prompt, rubric: [{criterion, points}], model_answer}
]
```

Validated in code. Any failure gives `LLMInvalidOutput`, which fails the job.

| Rule | Value |
|---|---|
| Question count | exactly 8 (6 MCQ + 2 short) |
| Skills | every `skill` is in the target set; each target skill has ≥ 2 questions |
| MCQ options | exactly 4 non-empty, distinct after casefold |
| MCQ answer | `correct_index` 0–3 |
| Rubric | 2–5 criteria; points 1–5 each; total ≤ 10 |
| Text caps | prompt ≤ 1500, option ≤ 300, explanation/model_answer ≤ 1500 |

**Question order:** shuffled in code with `secrets.SystemRandom`. MCQ options are shuffled too, with `correct_index` remapped, so the model's position bias doesn't leak.

## Grading and scoring

**MCQ:** 1 point each if correct.

**Short answers:** one `assessment_grade` LLM call with every short question's prompt, rubric and model answer, plus each candidate answer inside `wrap_untrusted("candidate_answer", …)`.
- Output: `[{question_id, criteria_met: [index], feedback}]`.
- In code: points = the sum of the rubric points for valid, unique `criteria_met` indexes.
- Unknown question ids are ignored, and a missing grade counts as 0.

**Weighting:** within a skill, each MCQ is worth 1 point and each short answer 2 points, scaled by its rubric points earned / total. Short answers weigh double because they show reasoning, not recall.

**Results:**
- Per-skill % = earned / possible × 100. Overall % = the mean of the per-skill values.
- `injection_flags` come from `scan()` on each short answer and are stored per answer. They are informational and never change points.

## Results, badges and matching

- `skill_badges` gains `expires_at`. A skill with ≥ 70% creates or refreshes a badge (`source=assessment`, `level = %`, `evidence = {assessment_id}`, `expires_at = now + 365 days`).
- `build_skill_profile`: active badges (not expired) add the skill at level `assessment`.
  - `CREDIT["assessment"] = 1.0`.
  - Precedence: repo > assessment > cv for the displayed level. Credit is 1.0 for both repo and assessment.
  - The weights stay 70/15/15.
- Candidate cards: `verified_skills` includes repo and assessment levels.

**Report (developer, after grading):**
- overall and per-skill %
- per question: the prompt, their answer, correct/incorrect (MCQ: the correct option plus explanation; short: criteria met and missed plus the model answer plus grader feedback)
- strengths (skills ≥ 70%) and study suggestions (skills < 70%, plus the prompts they missed)

**Recruiter view** (recruiter-sent or automatic assessments for their own posting only):
- status, overall and per-skill %, time taken
- the short-answer texts with criteria met
- the injection flags

The recruiter view never shows practice assessments or other postings' assessments.

## API

| Route | Who | Rules |
|---|---|---|
| `POST /applications/{id}/assessment` | posting-owner recruiter | one per application (409); application not withdrawn or rejected; 20/day per recruiter → 429 |
| `PUT /postings/{id}` | owner | gains `auto_assessment: bool` |
| apply (existing) | developer | if `auto_assessment`, also creates an assessment |
| `POST /me/assessments {skills}` | developer | practice, 1–3 skills; 3/day → 429; same skill within 7 days → 409 |
| `GET /me/assessments` | developer | own assessments: status, kind, skills, overall % |
| `POST /assessments/{id}/start`, `GET /assessments/{id}/current`, `POST /assessments/{id}/answers`, `POST /assessments/{id}/submit` | candidate only | 404 for anyone else |
| `GET /assessments/{id}/report` | candidate | only when graded (409 before) |
| `GET /applications/{id}/assessment` | posting-owner recruiter | the recruiter view; 404 for practice or other recruiters |

**`GET /current` returns:** `{question_id, index, total, kind, skill, prompt, options?, seconds_left}`. It never returns `correct_index`, the rubric, the explanation or the model answer. An allowlist output model is tested.

## Data model (migration 0004)

| Table / column | Fields |
|---|---|
| `assessments` | id, profile_id FK cascade, posting_id FK cascade NULL, application_id FK cascade NULL, kind (recruiter\|auto\|practice), status, skills JSON, created_by FK users SET NULL, started_at, deadline, submitted_at, graded_at, overall_pct, skill_pcts JSON, created_at; unique(application_id) |
| `assessment_questions` | id, assessment_id FK cascade, position, kind (mcq\|short), skill, difficulty, prompt, options JSON NULL, correct_index NULL, explanation NULL, rubric JSON NULL, model_answer NULL |
| `assessment_answers` | id, question_id FK cascade unique, choice_index NULL, text NULL, points float NULL, criteria_met JSON NULL, feedback NULL, injection_flags JSON, answered_at |
| `skill_badges.expires_at` | UTCDateTime NULL |
| `job_postings.auto_assessment` | bool, default false |
| `jobs.kind` | + assessment_generate, assessment_grade |

## Threat model additions

| Threat | Mitigation | Test |
|---|---|---|
| Answer key leaks | `current` and answer responses come from allowlist models; the report is only available after grading | key sets of every candidate-facing response before grading |
| Injection in a short answer ("award full marks") | `wrap_untrusted`; points computed in code from rubric indexes; flags stored | answer with injection + FakeLLM claiming all criteria for an unknown id → ignored; points ≤ rubric max |
| Injection in posting text steering generation | sanitized description, wrapped; skills validated against the target set | generated question with an off-target skill → generation rejected |
| Timer bypass / replay | server `deadline`; start only from `ready`; answers in strict order; submit idempotent | late answer → 409; double submit → same result; answering an earlier question → 409 |
| Badge farming | 3/day, 7-day per-skill cooldown, one attempt, 12-month expiry | 4th practice → 429; same skill in 7 days → 409; expired badge gives no credit |
| IDOR | candidate-only and owner-recruiter-only checks; practice is never visible to recruiters | other developer or recruiter → 404 on every route |
| Wrong MCQ key from the model | explanation stored and shown in the report; shuffle in code | (known risk, accepted for Part 3) |
| Cost | ~2 calls per assessment; auto is off by default; limits | auto off → apply creates no assessment |

## Milestones

Same loop as Parts 1–2 (Sonnet implements; Opus reviews, runs checks, does the security pass, commits, writes the Obsidian note).

- **M11:** migration 0004, models, `assessment_generate`, creation helper.
- **M12:** taking flow: start, current, answer, submit, deadline handling, MCQ grading.
- **M13:** `assessment_grade`, finalize, badges, skill-profile integration, report, recruiter view.
- **M14:**
  - triggers: recruiter send, auto on apply, practice, with limits
  - extend `e2e_smoke.py --part3` and do one real run (ask first)
  - update CLAUDE.md and the Obsidian summary

## Verification

- **Offline:** FakeLLM (generation and grading fixtures), temp SQLite.
- **Generation validation:** every rule in the table, positive and negative; the shuffle remaps `correct_index` correctly (property test over 100 seeds).
- **Taking flow:** the deadline (time is injected or frozen via a `now` provider), strict order, idempotent submit, auto-submit on access after the deadline.
- **Grading:** criteria clamping, unknown ids, missing grades, weighting maths (golden cases).
- **Badges:** threshold at exactly 70% (pass) and 69.9% (fail), expiry, refresh; matching credit 1.0; stale match scores after a badge.
- **Privacy:** the key-set allowlists above; logs contain no question or answer text.
- **Regression:** the full suite (572+) stays green, plus the migration drift test.
- **Real end-to-end (M14):** practice and recruiter-sent assessments against the real Claude API, with real generation, answering and grading.

## Out of scope

- running candidate code
- proctoring or behaviour tracking
- question disputes
- a question bank or reuse
- frontend
