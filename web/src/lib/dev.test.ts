/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { describe, expect, it } from "vitest";
import { breakdown, completeness, fieldErrors, groupSkills, languageShares } from "./dev";
import type { Overview } from "./devTypes";

const ov = (over: Partial<Overview> = {}): Overview => ({ verified: false, cv: null, repos: [], skills: [], ...over });

describe("completeness", () => {
  it("is 0% for an empty profile", () => {
    expect(completeness(ov(), undefined).percent).toBe(0);
  });
  it("counts parsed CV, analyzed repo and filled fields", () => {
    const r = completeness(
      ov({ cv: { id: "c", status: "parsed", job_id: null }, repos: [{ id: "r", owner: "a", name: "b", status: "done", job_id: null }] }),
      { headline: "h", bio: null, location: "TLV" } as never,
    );
    expect(r.items.filter((i) => i.done).map((i) => i.key)).toEqual(["cv", "repo", "headline", "location"]);
    expect(r.percent).toBe(57);
  });
  it("does not count a pending CV or a running repo", () => {
    const r = completeness(ov({ cv: { id: "c", status: "pending", job_id: null }, repos: [{ id: "r", owner: "a", name: "b", status: "running", job_id: null }] }), undefined);
    expect(r.percent).toBe(0);
  });
});

describe("languageShares", () => {
  it("sorts and computes proportions", () => {
    expect(languageShares({ Python: 750, Go: 250, Empty: 0 })).toEqual([
      { name: "Python", pct: 75 },
      { name: "Go", pct: 25 },
    ]);
  });
  it("handles missing and all-zero input", () => {
    expect(languageShares(undefined)).toEqual([]);
    expect(languageShares({ A: 0 })).toEqual([]);
  });
});

describe("breakdown", () => {
  it("applies 70/15/15 weights", () => {
    const rows = breakdown({ required_cov: 0.8, optional_cov: 0.5, tier_fit: 1, required: [], optional: [] });
    expect(rows.map((r) => r.points)).toEqual([56, 7.5, 15]);
    expect(rows.map((r) => r.weight)).toEqual([70, 15, 15]);
  });
});

describe("groupSkills", () => {
  it("groups by level and sorts by name", () => {
    const g = groupSkills([
      { skill: "go", level: "cv", years: null, sources: [] },
      { skill: "python", level: "repo", years: null, sources: [] },
      { skill: "c", level: "cv", years: 1, sources: [] },
    ]);
    expect(g.repo.map((s) => s.skill)).toEqual(["python"]);
    expect(g.cv.map((s) => s.skill)).toEqual(["c", "go"]);
    expect(g.assessment).toEqual([]);
  });
});

describe("fieldErrors", () => {
  it("maps pydantic errors to fields", () => {
    expect(fieldErrors(JSON.stringify([{ loc: ["body", "headline"], msg: "too long" }]))).toEqual({ headline: "too long" });
  });
  it("returns {} for plain text or garbage", () => {
    expect(fieldErrors("handle is taken")).toEqual({});
    expect(fieldErrors("null")).toEqual({});
  });
});
