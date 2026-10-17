/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
// Pure helpers for the developer screens (kept out of components so they are unit-testable).
import type { Schemas } from "./api";
import type { Components, Level, Overview, SkillEntry } from "./devTypes";

type Profile = Schemas["ProfileOut"];

export const POLL_MS = 1500;
export const MAX_PDF_BYTES = 5 * 1024 * 1024;
export const isActive = (s?: string | null) => s === "queued" || s === "running";

/** Profile completeness: CV parsed, >=1 repo analyzed, and the five profile fields. */
export const COMPLETENESS_KEYS = ["cv", "repo", "headline", "bio", "location", "experience_tier", "github_username"] as const;
export type CompletenessKey = (typeof COMPLETENESS_KEYS)[number];

export function completeness(ov: Overview, p: Profile | undefined) {
  const done: Record<CompletenessKey, boolean> = {
    cv: ov.cv?.status === "parsed",
    repo: ov.repos.some((r) => r.status === "done"),
    headline: !!p?.headline,
    bio: !!p?.bio,
    location: !!p?.location,
    experience_tier: !!p?.experience_tier,
    github_username: !!p?.github_username,
  };
  const items = COMPLETENESS_KEYS.map((key) => ({ key, done: done[key] }));
  const percent = Math.round((items.filter((i) => i.done).length / items.length) * 100);
  return { items, percent };
}

/** Skills by level, strongest evidence first; each group sorted by name. */
export function groupSkills(skills: SkillEntry[]): Record<Level, SkillEntry[]> {
  const out: Record<Level, SkillEntry[]> = { repo: [], assessment: [], cv: [] };
  for (const s of skills) out[s.level]?.push(s);
  for (const l of Object.keys(out) as Level[]) out[l].sort((a, b) => a.skill.localeCompare(b.skill));
  return out;
}

/** Languages bar segments: share of total bytes, largest first, one decimal. Empty if no bytes. */
export function languageShares(langs: Record<string, number> | undefined) {
  const entries = Object.entries(langs ?? {}).filter(([, n]) => n > 0);
  const total = entries.reduce((a, [, n]) => a + n, 0);
  return entries
    .sort((a, b) => b[1] - a[1])
    .map(([name, n]) => ({ name, pct: Math.round((n / total) * 1000) / 10 }));
}

const WEIGHTS = { required: 70, optional: 15, tier: 15 } as const;
/** Score breakdown rows: weight x coverage = points (the 70/15/15 formula). */
export function breakdown(c: Components) {
  const cov = { required: c.required_cov, optional: c.optional_cov, tier: c.tier_fit };
  return (Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[]).map((key) => ({
    key,
    weight: WEIGHTS[key],
    coverage: cov[key],
    points: Math.round(WEIGHTS[key] * cov[key] * 10) / 10,
  }));
}

/** FastAPI 422 detail (JSON-stringified by api()) -> { fieldName: message }. Non-field text -> {}. */
export function fieldErrors(detail: string): Record<string, string> {
  try {
    const arr = JSON.parse(detail);
    if (!Array.isArray(arr)) return {};
    const out: Record<string, string> = {};
    for (const e of arr) {
      const field = Array.isArray(e?.loc) ? String(e.loc[e.loc.length - 1]) : "";
      if (field && typeof e.msg === "string") out[field] ??= e.msg;
    }
    return out;
  } catch {
    return {};
  }
}

// Exact backend reasons we translate (key under dev.errors.reasons). Anything else falls back to the
// status-based generic text, so no untranslated English is appended in other locales.
const REASONS: [RegExp, string][] = [
  [/^demo limit reached for this sandbox$/, "demoLimit"],
  [/^daily match limit reached$/, "dailyMatch"],
  [/^daily practice limit reached$/, "dailyPractice"],
  [/^daily ranking limit reached$/, "dailyRank"],
  [/^daily assessment limit reached$/, "dailyAssessment"],
  [/^daily application limit reached$/, "dailyApplication"],
  [/^daily invitation limit reached$/, "dailyInvite"],
  [/^verify your profile first/, "verifyRequired"],
  [/^already applied$/, "alreadyApplied"],
  [/^already invited$/, "alreadyInvited"],
  [/^an assessment was already sent for this application$/, "assessmentSent"],
  [/^time is up$/, "timeUp"],
  [/^posting is closed$/, "postingClosed"],
  [/^practice for '(.+)' was taken in the last 7 days$/, "practiceCooldown"],
];

/** Known backend reason -> { key, skill? } (skill only for the cooldown message), else null. */
export function reasonKey(detail: string): { key: string; skill?: string } | null {
  for (const [re, key] of REASONS) {
    const m = re.exec(detail);
    if (m) return { key, skill: m[1] };
  }
  return null;
}
