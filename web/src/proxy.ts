/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
// Next 16 renamed "middleware" to "proxy"; this file is the middleware: next-intl routing plus
// the strict CSP (per-request nonce) and the other security headers.
import createMiddleware from "next-intl/middleware";
import type { NextRequest } from "next/server";
import { buildCsp } from "./lib/csp";
import { routing } from "./i18n/routing";

const intl = createMiddleware(routing);

export function proxy(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const csp = buildCsp(nonce, process.env.NODE_ENV === "development");
  // Next reads the nonce from the request's CSP header and stamps it on its own scripts.
  request.headers.set("x-nonce", nonce);
  request.headers.set("Content-Security-Policy", csp);
  const response = intl(request);
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  return response;
}

export const config = {
  // Everything except the API proxy, Next internals and files with an extension.
  matcher: ["/((?!api|_next|_vercel|opengraph-image|.*\\..*).*)"],
};
