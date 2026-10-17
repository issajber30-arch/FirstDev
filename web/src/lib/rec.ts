/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
// Pure helpers for the recruiter screens and the chip input.

export type AppStatus = "submitted" | "reviewing" | "interview" | "rejected" | "accepted" | "withdrawn";
// Mirrors ALLOWED_TRANSITIONS in firstdev/api/applications.py.
const NEXT: Partial<Record<AppStatus, AppStatus[]>> = {
  submitted: ["reviewing", "rejected"],
  reviewing: ["interview", "rejected"],
  interview: ["accepted", "rejected"],
};
export const nextStates = (s: AppStatus): AppStatus[] => NEXT[s] ?? [];

/** Add the comma-separated tokens in `raw` to `list`: trimmed, case-insensitive de-dupe, capped. */
export function addChips(list: string[], raw: string, max: number, maxLen = 60): string[] {
  const out = [...list];
  for (const tok of raw.split(",")) {
    const v = tok.trim().slice(0, maxLen);
    if (v && out.length < max && !out.some((x) => x.toLowerCase() === v.toLowerCase())) out.push(v);
  }
  return out;
}

/** Short text label for a loosely typed injection flag (rendered as text only). */
export const flagLabel = (f: Record<string, unknown>): string => String(f.kind ?? f.pattern ?? f.type ?? "flag").slice(0, 40);
