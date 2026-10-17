/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import en from "../src/messages/en.json";

// Assessment and recruiter pages (M21) are appended here as [role, path] pairs.
const M21_PAGES: [("dev" | "rec"), string][] = [];

const PUBLIC = ["/en", "/he", "/en/sign-in", "/he/sign-in", "/en/join", "/he/join"];
const DEV = ["", "/profile", "/cv", "/repos", "/jobs", "/applications", "/invitations", "/connections"].map((p) => `/dev${p}`);

async function audit(page: Page, path: string, bad: string[]) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(page.getByText(en.common.loading)).toHaveCount(0, { timeout: 15_000 });
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  for (const v of violations) {
    const line = `${path} [${v.impact}] ${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")} (${v.nodes.length} nodes)`;
    if (v.impact === "serious" || v.impact === "critical") bad.push(line);
    else console.log(`axe minor: ${line}`);
  }
}

async function sandbox(page: Page, button: string, url: string) {
  await page.context().clearCookies();
  await page.goto("/en");
  await page.getByRole("button", { name: button }).click();
  await page.waitForURL(url);
}

test("axe: public pages and developer screens have no serious/critical violations", async ({ page }) => {
  const bad: string[] = [];
  for (const p of PUBLIC) await audit(page, p, bad);
  await sandbox(page, en.landing.tryDeveloper, "**/en/dev");
  for (const p of ["/en", "/he"]) for (const d of DEV) await audit(page, `${p}${d}`, bad);
  await page.goto("/en/dev/jobs");
  await page.getByRole("link", { name: en.dev.jobs.details }).first().click();
  await page.waitForURL(/\/en\/dev\/jobs\/[^/]+$/);
  await expect(page.getByRole("heading", { name: en.dev.match.breakdown })).toBeVisible({ timeout: 60_000 });
  await audit(page, new URL(page.url()).pathname, bad);
  expect(bad, bad.join("\n")).toEqual([]);
});

test("axe: M21 pages", async ({ page }) => {
  test.skip(M21_PAGES.length === 0, "no M21 pages registered yet");
  const bad: string[] = [];
  for (const role of ["dev", "rec"] as const) {
    const pages = M21_PAGES.filter(([r]) => r === role);
    if (!pages.length) continue;
    await sandbox(page, role === "dev" ? en.landing.tryDeveloper : en.landing.tryRecruiter, `**/en/${role}`);
    for (const [, p] of pages) for (const l of ["en", "he"]) await audit(page, `/${l}${p}`, bad);
  }
  expect(bad, bad.join("\n")).toEqual([]);
});
