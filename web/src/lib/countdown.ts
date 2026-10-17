/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
// Pure countdown logic for the assessment timer. The server's `seconds_left` is the truth: every
// response re-syncs a local deadline, and a 1 s interval only reads the clock (no drift accrues).

/** Announce (aria-live) when the clock first reaches these many seconds, most urgent first. */
export const ANNOUNCE_AT = [30, 60, 300] as const;
export const URGENT_BELOW = 60;

/** Absolute deadline (ms epoch) from a server `seconds_left` received at `now`. */
export const deadlineFrom = (secondsLeft: number, now: number) => now + Math.max(0, secondsLeft) * 1000;

/** Whole seconds left, rounded up so "0" means expired and never shows early. */
export const secondsLeft = (deadline: number, now: number) => Math.max(0, Math.ceil((deadline - now) / 1000));

/** The threshold crossed going from `prev` to `next` seconds (smallest one if several), else null. */
export const crossed = (prev: number, next: number): number | null =>
  ANNOUNCE_AT.find((t) => prev > t && next <= t) ?? null;

export const isUrgent = (s: number) => s < URGENT_BELOW;

export function formatClock(s: number): string {
  const n = Math.max(0, Math.floor(s));
  return `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;
}

/** Warning pulse only when urgent AND motion is allowed; reduced motion gets a static style. */
export const pulseClass = (s: number, reducedMotion: boolean) => (isUrgent(s) && !reducedMotion ? "animate-pulse" : "");
