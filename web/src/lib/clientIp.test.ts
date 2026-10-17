/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { describe, expect, it } from "vitest";
import { clientIp } from "./clientIp";

describe("clientIp", () => {
  it("ignores X-Forwarded-For entirely when no trusted proxy is configured", () => {
    expect(clientIp("6.6.6.6", 0)).toBeNull();
  });
  it("takes the entry appended by the trusted proxy, not the client's", () => {
    // Client spoofed "6.6.6.6"; the trusted front end appended the real address.
    expect(clientIp("6.6.6.6, 203.0.113.7", 1)).toBe("203.0.113.7");
    expect(clientIp("6.6.6.6, 203.0.113.7, 10.0.0.1", 2)).toBe("203.0.113.7");
  });
  it("returns null when the header has fewer entries than trusted hops", () => {
    expect(clientIp("", 1)).toBeNull();
    expect(clientIp(null, 1)).toBeNull();
    expect(clientIp("203.0.113.7", 2)).toBeNull();
  });
});
