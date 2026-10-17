/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { expect, test } from "@playwright/test";
import en from "../src/messages/en.json";

// Runs against the production build: the CSP must not allow 'unsafe-eval'.
test("HTML responses: nonce CSP, nosniff, referrer policy, every script nonced", async ({ request }) => {
  for (const path of ["/en", "/he", "/en/sign-in", "/en/join"]) {
    const res = await request.get(path);
    const csp = res.headers()["content-security-policy"] ?? "";
    const nonce = /'nonce-([^']+)'/.exec(csp)?.[1];
    expect(nonce, `${path} CSP nonce`).toBeTruthy();
    expect(csp).not.toContain("unsafe-eval");
    expect(res.headers()["x-content-type-options"]).toBe("nosniff");
    expect(res.headers()["referrer-policy"]).toBeTruthy();
    const scripts = [...(await res.text()).matchAll(/<script\b[^>]*>/g)].map((m) => m[0]);
    expect(scripts.length).toBeGreaterThan(0);
    for (const tag of scripts) expect(tag, `${path} script without nonce`).toContain(`nonce="${nonce}"`);
  }
});

test("API responses keep the backend security headers", async ({ request }) => {
  const res = await request.get("/api/health");
  expect(res.status()).toBe(200);
  const h = res.headers();
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["content-security-policy"]).toContain("default-src 'none'");
  expect(h["referrer-policy"]).toBe("no-referrer");
});

test("session cookies and CSRF enforcement", async ({ page }) => {
  await page.goto("/en");
  await page.getByRole("button", { name: en.landing.tryDeveloper }).click();
  await page.waitForURL("**/en/dev");
  const cookies = Object.fromEntries((await page.context().cookies()).map((c) => [c.name, c]));
  expect(cookies.fd_access.httpOnly).toBe(true);
  expect(cookies.fd_refresh.httpOnly).toBe(true);
  expect(cookies.fd_refresh.path).toBe("/api/auth");
  expect(cookies.fd_csrf.httpOnly).toBe(false);
  // Cookie-authenticated write without the CSRF header is refused.
  const res = await page.request.post("/api/profiles/me/cv", { data: { text: "x" } });
  expect(res.status()).toBe(403);
});
