/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */

/**
 * The visitor's IP, or null when it can't be known safely.
 *
 * X-Forwarded-For is a list: anything a client sends comes first, and each trusted proxy in
 * front of us appends the address it saw. Next.js only fills the header when it is absent,
 * so with no trusted proxy (local dev) the whole value may be client-controlled and is
 * ignored. FIRSTDEV_TRUSTED_PROXY_HOPS = number of trusted proxies that append (Cloud Run: 1).
 */
export function clientIp(xForwardedFor: string | null, hops = trustedHops()): string | null {
  if (hops < 1) return null;
  const parts = (xForwardedFor ?? "").split(",").map((p) => p.trim()).filter(Boolean);
  if (parts.length < hops) return null;
  return parts[parts.length - hops] ?? null;
}

function trustedHops(): number {
  const n = Number.parseInt(process.env.FIRSTDEV_TRUSTED_PROXY_HOPS ?? "0", 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}
