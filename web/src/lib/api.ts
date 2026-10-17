/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
// Typed fetch wrapper for the same-origin /api proxy. Auth is cookie-only: no tokens in JS.
import type { components } from "./api-types";

export type Schemas = components["schemas"];
export type Me = Schemas["UserOut"];

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// Auth/demo endpoints report their own 401s (wrong password...); they never trigger a refresh.
const NO_REFRESH = /^\/(auth|demo)\//;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

/** Replaceable so tests (and nothing else) can observe the redirect. */
export const nav = {
  toSignIn() {
    const locale = window.location.pathname.split("/")[1] === "he" ? "he" : "en";
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- full reload is intended
    window.location.href = `/${locale}/sign-in`; // hard navigation: drops all cached state
  },
};

function csrfToken(): string | undefined {
  const m = document.cookie.match(/(?:^|;\s*)fd_csrf=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : undefined;
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = {};
  const form = body instanceof FormData; // multipart: the browser sets the boundary header
  if (body !== undefined && !form) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method)) {
    const t = csrfToken();
    if (t) headers["X-CSRF-Token"] = t;
  }
  return fetch(`/api${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
}

// Concurrent 401s share one refresh: the refresh token rotates, so a second call would look like reuse.
let refreshing: Promise<boolean> | null = null;
function refresh(): Promise<boolean> {
  refreshing ??= send("POST", "/auth/refresh")
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function fail(res: Response): Promise<never> {
  let detail = res.statusText;
  try {
    const j = await res.json();
    detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
  } catch {
    /* non-JSON error body: keep statusText */
  }
  throw new ApiError(res.status, detail);
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  let res = await send(method, path, body);
  if (res.status === 401 && !NO_REFRESH.test(path)) {
    // One refresh, one retry. A second 401 ends the session; there is no loop.
    if (await refresh()) res = await send(method, path, body);
    if (res.status === 401) {
      nav.toSignIn();
      throw new ApiError(401, "session expired");
    }
  }
  if (!res.ok) await fail(res);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const fetcher = <T>(path: string) => api<T>("GET", path);
