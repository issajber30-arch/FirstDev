/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { expect, test, type Page } from "@playwright/test";
import en from "../src/messages/en.json";
import he from "../src/messages/he.json";

const MSG = { en, he } as const;
const SHOTS = "e2e/screenshots";

// [path, key of the page's <h1> in dev.*]
const SCREENS: [string, string][] = [
  ["/dev", "dashboard.title"],
  ["/dev/profile", "profile.title"],
  ["/dev/cv", "cv.title"],
  ["/dev/repos", "repos.title"],
  ["/dev/jobs", "jobs.title"],
  ["/dev/applications", "applications.title"],
  ["/dev/invitations", "invitations.title"],
  ["/dev/connections", "connections.title"],
];

const get = (o: unknown, path: string) => path.split(".").reduce<unknown>((a, k) => (a as Record<string, unknown>)[k], o) as string;
const dev = (locale: "en" | "he", key: string) => get(MSG[locale].dev, key);

const CV_TEXT = `Dana Cohen
Backend developer
Experience
Python Developer, Acme Ltd, 2022-01 to present
Built REST APIs with Python and FastAPI on PostgreSQL. Wrote tests with pytest and used Docker and Git daily.
Education
B.Sc. Computer Science, Tel Aviv University, 2018 to 2021
Skills: Python, FastAPI, PostgreSQL, Docker, Git`;

test("developer screens: sandbox, every screen in en and he, CV parse, match detail", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text()}`));
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      // Surfaced through console.error so the listener above records it.
      console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI}`);
    });
  });

  // Sandbox from the landing page.
  await page.goto("/en");
  await page.getByRole("button", { name: en.landing.tryDeveloper }).click();
  await page.waitForURL("**/en/dev");

  for (const locale of ["en", "he"] as const) {
    for (const [path, key] of SCREENS) {
      await page.goto(`/${locale}${path}`);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(dev(locale, key));
      await expect(page.getByText(MSG[locale].common.loading)).toHaveCount(0, { timeout: 15_000 });
      await expect(page.locator("html")).toHaveAttribute("dir", locale === "he" ? "rtl" : "ltr");
      await expectNoHorizontalOverflow(page);
      await page.screenshot({ path: `${SHOTS}/${locale}${path.replace(/\//g, "-") || "-"}.png`, fullPage: true });
    }
  }

  // Paste a CV and wait for the parsed result (fake LLM mode).
  await page.goto("/en/dev/cv");
  await page.getByLabel(en.dev.cv.paste).fill(CV_TEXT);
  const posted = page.waitForResponse((r) => r.url().endsWith("/api/profiles/me/cv") && r.request().method() === "POST");
  await page.getByRole("button", { name: en.dev.cv.submit }).click();
  expect([200, 202], "CV upload status (429 = sandbox demo limit)").toContain((await posted).status());
  await expect(page.getByText(en.dev.cv.queued)).toBeVisible(); // 429 demo limit would show an alert instead
  // The fixture CV already shows "Done"; the new one must pass through to done with nothing in flight.
  await expect(page.getByText(en.dev.jobStatus.queued, { exact: true })).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByText(en.dev.jobStatus.running, { exact: true })).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByText(en.dev.jobStatus.done, { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: en.dev.cv.skills })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/en-dev-cv-parsed.png`, fullPage: true });

  // Profile: an API validation error shows inline, then a valid save succeeds.
  await page.goto("/en/dev/profile");
  await page.getByLabel(en.dev.profile.github).fill("-not valid-");
  await page.getByRole("button", { name: en.dev.profile.save }).click();
  await expect(page.getByRole("alert").filter({ hasText: /GitHub username|invalid/i }).first()).toBeVisible();
  await expect(page.getByText(en.dev.profile.fixFields)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/en-dev-profile-error.png`, fullPage: true });
  await page.getByLabel(en.dev.profile.github).fill("octocat");
  await page.getByRole("button", { name: en.dev.profile.save }).click();
  await expect(page.getByText(en.dev.profile.saved)).toBeVisible();

  // Match detail from the first recommended job.
  await page.goto("/en/dev/jobs");
  await page.getByRole("link", { name: en.dev.jobs.details }).first().click();
  await page.waitForURL(/\/en\/dev\/jobs\/[^/]+$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(en.dev.match.title);
  await expect(page.getByRole("heading", { name: en.dev.match.breakdown })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: en.dev.match.feedback })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/en-dev-match.png`, fullPage: true });
  const matchUrl = page.url();
  // Apply, then withdraw from the applications list.
  await page.getByRole("button", { name: en.dev.match.apply }).click();
  await expect(page.getByText(en.dev.match.applied)).toBeVisible();
  await page.getByRole("link", { name: en.dev.match.viewApplications }).click();
  await expect(page.getByText(en.dev.applications.status.submitted, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(en.dev.applications.withdraw) }).first().click();
  await expect(page.getByText(en.dev.applications.status.withdrawn, { exact: true })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/en-dev-applications-withdrawn.png`, fullPage: true });
  await page.goto(matchUrl.replace("/en/", "/he/"));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(he.dev.match.title);
  await expect(page.getByRole("heading", { name: he.dev.match.breakdown })).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: `${SHOTS}/he-dev-match.png`, fullPage: true });

  // Phone width, both directions.
  await page.setViewportSize({ width: 360, height: 800 });
  for (const p of ["/en/dev", "/he/dev/jobs", "/he/dev/repos"]) {
    await page.goto(p);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText(en.common.loading)).toHaveCount(0, { timeout: 15_000 });
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: `${SHOTS}/mobile${p.replace(/\//g, "-")}.png`, fullPage: true });
  }

  // The 422 above is an expected failed request, which Chrome logs as a console error.
  const unexpected = problems.filter((p) => !/status of 422/.test(p));
  expect(unexpected, unexpected.join("\n")).toEqual([]);
});

async function expectNoHorizontalOverflow(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over, "horizontal page overflow (px)").toBeLessThanOrEqual(0);
}
