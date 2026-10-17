/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */

export function buildCsp(nonce: string, dev: boolean): string {
  return [
    "default-src 'self'",
    // 'unsafe-eval' is needed only by Next's dev runtime (React debug stacks, HMR); never in production.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' https://challenges.cloudflare.com${dev ? " 'unsafe-eval'" : ""}`,
    "frame-src https://challenges.cloudflare.com",
    "connect-src 'self'",
    "img-src 'self' data:",
    "style-src 'self' 'unsafe-inline'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
  ].join("; ");
}
