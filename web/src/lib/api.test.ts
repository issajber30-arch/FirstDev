/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, nav } from "./api";

const json = (status: number, body: unknown = {}) =>
  new Response(status === 204 ? null : JSON.stringify(body), { status });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "fd_csrf=tok123";
  vi.spyOn(nav, "toSignIn").mockImplementation(() => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.cookie = "fd_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

const headersOf = (call: number) => fetchMock.mock.calls[call][1].headers as Record<string, string>;

describe("api", () => {
  it("echoes fd_csrf as X-CSRF-Token on unsafe methods only", async () => {
    fetchMock.mockImplementation(async () => json(200));
    await api("POST", "/x", { a: 1 });
    await api("GET", "/x");
    expect(headersOf(0)["X-CSRF-Token"]).toBe("tok123");
    expect(headersOf(1)["X-CSRF-Token"]).toBeUndefined();
  });

  it("refreshes once on 401 and retries once", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401))
      .mockResolvedValueOnce(json(204)) // refresh
      .mockResolvedValueOnce(json(200, { ok: true }));
    expect(await api("GET", "/me")).toEqual({ ok: true });
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/me", "/api/auth/refresh", "/api/me"]);
    expect(nav.toSignIn).not.toHaveBeenCalled();
  });

  it("does not loop: second 401 redirects to sign-in", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401))
      .mockResolvedValueOnce(json(204)) // refresh succeeds
      .mockResolvedValueOnce(json(401)); // retry still 401
    await expect(api("GET", "/me")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(3); // request, refresh, one retry
    expect(nav.toSignIn).toHaveBeenCalledOnce();
  });

  it("redirects without retrying when the refresh itself fails", async () => {
    fetchMock.mockResolvedValueOnce(json(401)).mockResolvedValueOnce(json(401));
    await expect(api("GET", "/me")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(nav.toSignIn).toHaveBeenCalledOnce();
  });

  it("does not refresh or redirect on a login 401", async () => {
    fetchMock.mockResolvedValue(json(401, { detail: "invalid credentials" }));
    await expect(api("POST", "/auth/login", {})).rejects.toMatchObject({ detail: "invalid credentials" });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(nav.toSignIn).not.toHaveBeenCalled();
  });
});
