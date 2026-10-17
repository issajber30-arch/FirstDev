/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { describe, expect, it } from "vitest";
import { addChips, nextStates } from "./rec";

describe("nextStates", () => {
  it("offers only allowed transitions", () => {
    expect(nextStates("submitted")).toEqual(["reviewing", "rejected"]);
    expect(nextStates("interview")).toEqual(["accepted", "rejected"]);
    expect(nextStates("accepted")).toEqual([]);
    expect(nextStates("withdrawn")).toEqual([]);
  });
});

describe("addChips", () => {
  it("splits on commas, trims, dedupes case-insensitively", () => {
    expect(addChips(["Python"], " python, FastAPI ,, ,Go", 10)).toEqual(["Python", "FastAPI", "Go"]);
  });
  it("respects the cap and ignores empty input", () => {
    expect(addChips(["a", "b"], "c,d", 3)).toEqual(["a", "b", "c"]);
    expect(addChips(["a"], "  ", 3)).toEqual(["a"]);
  });
});
