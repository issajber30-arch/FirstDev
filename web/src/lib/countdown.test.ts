/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { describe, expect, it } from "vitest";
import { crossed, deadlineFrom, formatClock, isUrgent, pulseClass, secondsLeft } from "./countdown";

describe("countdown", () => {
  it("syncs a deadline from the server and ticks locally", () => {
    const d = deadlineFrom(90, 1_000_000);
    expect(secondsLeft(d, 1_000_000)).toBe(90);
    expect(secondsLeft(d, 1_000_000 + 1_000)).toBe(89);
    expect(secondsLeft(d, 1_000_000 + 1_500)).toBe(89); // rounds up: no early zero
  });
  it("re-sync replaces the local estimate (server wins)", () => {
    const local = deadlineFrom(90, 0);
    const resynced = deadlineFrom(70, 5_000); // server says 70 left at t=5s, local thought 85
    expect(secondsLeft(local, 5_000)).toBe(85);
    expect(secondsLeft(resynced, 5_000)).toBe(70);
  });
  it("expires at zero and never goes negative", () => {
    const d = deadlineFrom(2, 0);
    expect(secondsLeft(d, 2_000)).toBe(0);
    expect(secondsLeft(d, 60_000)).toBe(0);
    expect(secondsLeft(deadlineFrom(-5, 0), 0)).toBe(0);
  });
  it("announces 5 min, 1 min and 30 s once each", () => {
    expect(crossed(301, 300)).toBe(300);
    expect(crossed(300, 299)).toBeNull();
    expect(crossed(61, 60)).toBe(60);
    expect(crossed(31, 30)).toBe(30);
    expect(crossed(500, 20)).toBe(30); // a long gap (tab asleep) announces the most urgent one
  });
  it("urgent under 60 s; reduced motion gets no animation", () => {
    expect(isUrgent(59)).toBe(true);
    expect(isUrgent(60)).toBe(false);
    expect(pulseClass(30, false)).toBe("animate-pulse");
    expect(pulseClass(30, true)).toBe("");
    expect(pulseClass(120, false)).toBe("");
  });
  it("formats mm:ss", () => {
    expect(formatClock(1200)).toBe("20:00");
    expect(formatClock(65)).toBe("01:05");
    expect(formatClock(-3)).toBe("00:00");
  });
});
