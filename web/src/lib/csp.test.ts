/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { describe, expect, it } from "vitest";
import { buildCsp } from "./csp";

describe("buildCsp", () => {
  it("carries the nonce and the strict directives", () => {
    const csp = buildCsp("abc", false);
    expect(csp).toContain("'nonce-abc' 'strict-dynamic'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("base-uri 'none'");
  });
  it("allows unsafe-eval only in development", () => {
    expect(buildCsp("n", true)).toContain("'unsafe-eval'");
    expect(buildCsp("n", false)).not.toContain("'unsafe-eval'");
  });
});
