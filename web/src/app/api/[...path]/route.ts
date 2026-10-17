/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
// Same-origin proxy to the FastAPI backend: /api/x -> FIRSTDEV_API_URL/x. Keeps cookies
// first-party (no CORS) and lets the backend trust the client IP via a shared secret.
import type { NextRequest } from "next/server";

export const runtime = "nodejs";

const MAX_BODY = 6 * 1024 * 1024;
const TIMEOUT_MS = 30_000;
// Allowlist: the incoming Authorization header (and everything else) is never forwarded.
const FORWARD = ["cookie", "content-type", "x-csrf-token", "accept"];
const BODYLESS = new Set(["GET", "HEAD"]);

const text = (status: number, detail: string) =>
  Response.json({ detail }, { status });

/** Reads the body, refusing anything over MAX_BODY without buffering the excess. */
async function readBody(req: NextRequest): Promise<Uint8Array | null | "too-large"> {
  const declared = Number(req.headers.get("content-length") ?? 0);
  if (declared > MAX_BODY) return "too-large";
  if (!req.body) return null;
  const chunks: Uint8Array[] = [];
  let size = 0;
  const reader = req.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY) {
      await reader.cancel();
      return "too-large";
    }
    chunks.push(value);
  }
  const out = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.byteLength;
  }
  return size ? out : null;
}

async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  if (path.some((s) => s === "." || s === ".." || s.includes("/") || s.includes("\\"))) {
    return text(400, "bad path");
  }
  const base = (process.env.FIRSTDEV_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
  const url = `${base}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARD) {
    const v = req.headers.get(name);
    if (v) headers.set(name, v);
  }
  const secret = process.env.FIRSTDEV_PROXY_SECRET;
  if (secret) headers.set("x-firstdev-proxy-secret", secret);
  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0]?.trim();
  if (ip) headers.set("x-firstdev-client-ip", ip);

  let body: Uint8Array | null = null;
  if (!BODYLESS.has(req.method)) {
    const read = await readBody(req);
    if (read === "too-large") return text(413, "request body too large");
    body = read;
  }

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers,
      body: body as BodyInit | null,
      redirect: "manual",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (e) {
    const timedOut = e instanceof DOMException && e.name === "TimeoutError";
    return text(timedOut ? 504 : 502, timedOut ? "upstream timeout" : "upstream unavailable");
  }

  const out = new Headers();
  for (const name of ["content-type", "cache-control", "retry-after", "www-authenticate"]) {
    const v = upstream.headers.get(name);
    if (v) out.set(name, v);
  }
  // Several cookies must stay several headers; a joined string would corrupt them.
  for (const c of upstream.headers.getSetCookie()) out.append("set-cookie", c);
  const empty = upstream.status === 204 || upstream.status === 304 || req.method === "HEAD";
  return new Response(empty ? null : upstream.body, { status: upstream.status, headers: out });
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE, handle as HEAD, handle as OPTIONS };
