/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { expect, test, type Page } from "@playwright/test";
import en from "../src/messages/en.json";
import he from "../src/messages/he.json";

const MSG = { en, he } as const;
const SHOTS = "e2e/screenshots";
const LOCALES = ["en", "he"] as const;

const fmt = (s: string, v: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k) => String(v[k]));

/** Collects console errors, page errors and CSP violations; `allow` filters expected failed requests by URL. */
function watch(page: Page, allow: RegExp[] = []) {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const url = m.location().url;
    if (allow.some((re) => re.test(url))) return;
    problems.push(`console: ${m.text()} @ ${url}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  void page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI}`);
    });
  });
  return problems;
}

async function noOverflow(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over, "horizontal page overflow (px)").toBeLessThanOrEqual(0);
}

// The API allows 3 demo sandboxes per client IP per day. The Next.js dev proxy takes the IP from the first
// X-Forwarded-For entry, so each test names its own (RFC 5737 range) and reruns do not hit the limit.
const runId = Math.floor(Math.random() * 250) + 1;
let ipSeq = 0;
const ownIp = (page: Page) => page.context().setExtraHTTPHeaders({ "x-forwarded-for": `198.51.${runId}.${++ipSeq}` });

for (const locale of LOCALES) {
  const m = MSG[locale];

  test(`developer: practice assessment end to end [${locale}]`, async ({ page }) => {
    test.setTimeout(300_000);
    const problems = watch(page);
    await ownIp(page);
    await page.goto(`/${locale}`);
    await page.getByRole("button", { name: m.landing.tryDeveloper }).click();
    await page.waitForURL(`**/${locale}/dev`);

    await page.goto(`/${locale}/dev/assessments`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(m.dev.assess.title);
    await expect(page.getByText(m.common.loading)).toHaveCount(0, { timeout: 15_000 });
    await expect(page.getByText(m.dev.assess.empty)).toBeVisible();
    // Edge: no skill -> inline error, nothing is created.
    await page.getByRole("button", { name: m.dev.assess.start }).click();
    await expect(page.getByRole("alert").filter({ hasText: m.dev.assess.needSkill })).toBeVisible();
    await noOverflow(page);
    await page.screenshot({ path: `${SHOTS}/${locale}-dev-assessments.png`, fullPage: true });

    const chips = page.getByLabel(m.dev.assess.skillsLabel);
    await chips.fill("python");
    await chips.press("Enter");
    await expect(page.getByRole("button", { name: fmt(m.dev.assess.removeSkill, { skill: "python" }) })).toBeVisible();
    await page.getByRole("button", { name: m.dev.assess.start }).click();
    await page.waitForURL(/\/dev\/assessments\/[^/]+$/);

    // generating -> ready (worker, fake LLM)
    await page.getByRole("button", { name: m.dev.assess.begin }).click({ timeout: 90_000 });
    for (let i = 0; i < 8; i++) {
      const heading = page.getByRole("heading", { level: 2, name: fmt(m.dev.assess.questionOf, { n: i + 1, total: 8 }) });
      await expect(heading).toBeVisible({ timeout: 30_000 });
      await expect(heading, "focus moves to the new question heading").toBeFocused();
      await expect(page.getByRole("timer")).toBeVisible();
      const radios = page.getByRole("radio");
      const mcq = (await radios.count()) > 0;
      if (mcq) {
        await expect(page.getByRole("group")).toBeVisible(); // radio group semantics: fieldset + legend
        await radios.first().check();
      } else {
        const box = page.getByLabel(m.dev.assess.shortLabel);
        await box.fill("I would validate the input, handle errors explicitly and write tests for the edge cases.");
        await expect(page.getByText(fmt(m.dev.assess.counter, { n: 88, max: 2000 }))).toBeVisible();
      }
      if (i === 0 || !mcq) await page.screenshot({ path: `${SHOTS}/${locale}-dev-assessment-${mcq ? "mcq" : "short"}.png`, fullPage: true });
      await page.getByRole("button", { name: m.dev.assess.submitAnswer }).click();
    }

    // submitted -> graded -> redirected to the report
    await page.waitForURL(/\/report$/, { timeout: 120_000 });
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(m.dev.assess.report.title);
    await expect(page.getByRole("heading", { name: m.dev.assess.report.perSkill })).toBeVisible();
    expect(await page.getByRole("meter").count(), "overall + per-skill bars").toBeGreaterThanOrEqual(2);
    await expect(page.getByTestId("review").locator("> li")).toHaveCount(8);
    await noOverflow(page);
    await page.screenshot({ path: `${SHOTS}/${locale}-dev-assessment-report.png`, fullPage: true });

    // The list now shows the graded assessment with its percentage.
    await page.goto(`/${locale}/dev/assessments`);
    await expect(page.getByRole("link", { name: m.dev.assess.viewReport })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/${locale}-dev-assessments-graded.png`, fullPage: true });
    expect(problems, problems.join("\n")).toEqual([]);
  });

  test(`recruiter: postings, applicants, candidates, create [${locale}]`, async ({ page }) => {
    test.setTimeout(300_000);
    const problems = watch(page, [/\/applications\/[^/]+\/assessment$/]); // 404 = "no assessment sent"
    await ownIp(page);
    await page.goto(`/${locale}`);
    await page.getByRole("button", { name: m.landing.tryRecruiter }).click();
    await page.waitForURL(`**/${locale}/rec`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(m.rec.postings.title);
    await expect(page.getByText(m.common.loading)).toHaveCount(0, { timeout: 15_000 });
    await noOverflow(page);
    await page.screenshot({ path: `${SHOTS}/${locale}-rec-postings.png`, fullPage: true });

    await page.locator("h2 a").first().click();
    await page.waitForURL(/\/rec\/postings\/[^/]+$/);
    const postingUrl = page.url();
    await expect(page.getByRole("tab", { name: m.rec.tabs.applicants })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText(m.common.loading)).toHaveCount(0, { timeout: 15_000 });
    await page.screenshot({ path: `${SHOTS}/${locale}-rec-applicants.png`, fullPage: true });
    const viewBtn = page.getByRole("button", { name: m.rec.applicants.viewAssessment }).first();
    if (await viewBtn.count()) {
      await viewBtn.click();
      await expect(page.getByText(m.rec.applicants.noAssessment).or(page.getByRole("heading", { name: m.rec.applicants.assessment }))).toBeVisible();
    }

    // Candidates tab: keyboard-reachable tab, then Rank -> job done -> cards.
    await page.getByRole("tab", { name: m.rec.tabs.candidates }).click();
    await page.getByRole("button", { name: m.rec.candidates.rank }).click();
    await expect(page.getByText(m.dev.jobStatus.done, { exact: true })).toBeVisible({ timeout: 90_000 });
    const invite = page.getByRole("button", { name: m.rec.candidates.invite });
    await expect(invite.first()).toBeVisible({ timeout: 15_000 });
    await noOverflow(page);
    await page.screenshot({ path: `${SHOTS}/${locale}-rec-candidates.png`, fullPage: true });
    await invite.first().click();
    await expect(page.getByRole("button", { name: m.rec.candidates.invited }).first()).toBeDisabled();

    // Create a posting with chips: Enter and comma add, Backspace removes, auto-assessment is hidden in sandboxes.
    await page.goto(`/${locale}/rec/postings/new`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(m.rec.form.newTitle);
    await expect(page.getByLabel(m.rec.form.autoAssessment)).toHaveCount(0);
    await page.getByRole("button", { name: m.rec.form.publish }).click(); // edge: empty form
    await expect(page.getByText(m.rec.form.errTitle)).toBeVisible();
    await expect(page.getByText(m.rec.form.errRequired)).toBeVisible();
    const title = `E2E Backend Engineer ${locale}`;
    await page.getByLabel(m.rec.form.title, { exact: true }).fill(title);
    await page.getByLabel(m.rec.form.description).fill("Build and maintain Python services with tests.");
    const req = page.getByLabel(m.rec.form.required);
    await req.fill("python");
    await req.press("Enter");
    await req.pressSequentially("fastapi,"); // a real comma keystroke commits the chip
    await req.fill("temp");
    await req.press("Enter");
    await req.press("Backspace");
    await expect(page.getByRole("button", { name: fmt(m.rec.form.removeSkill, { skill: "temp" }) })).toHaveCount(0);
    await expect(page.getByRole("button", { name: fmt(m.rec.form.removeSkill, { skill: "fastapi" }) })).toBeVisible();
    await page.getByLabel(m.rec.form.optional).fill("docker");
    await page.getByLabel(m.rec.form.optional).press("Enter");
    await page.getByLabel(m.rec.form.location).fill("Tel Aviv");
    await noOverflow(page);
    await page.screenshot({ path: `${SHOTS}/${locale}-rec-posting-form.png`, fullPage: true });
    await page.getByRole("button", { name: m.rec.form.publish }).click();
    await page.waitForURL(/\/rec\/postings\/[^/]+$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
    await expect(page.getByText(m.rec.status.open, { exact: true })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/${locale}-rec-posting-created.png`, fullPage: true });

    // Phone width on the candidates list.
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`${postingUrl}?tab=candidates`);
    await expect(page.getByRole("tab", { name: m.rec.tabs.candidates })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText(m.common.loading)).toHaveCount(0, { timeout: 15_000 });
    await noOverflow(page);
    await page.screenshot({ path: `${SHOTS}/mobile-${locale}-rec-candidates.png`, fullPage: true });
    expect(problems, problems.join("\n")).toEqual([]);
  });

  test(`public profile: unknown handle is a 404 [${locale}]`, async ({ page }) => {
    const problems = watch(page, [/\/u\/no-such-handle-xyz$/]); // the 404 document itself is logged by Chrome
    const res = await page.goto(`/${locale}/u/no-such-handle-xyz`);
    expect(res?.status()).toBe(404);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(m.pub.notFoundTitle);
    await expect(page.getByText(m.pub.notFoundBody)).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("dir", locale === "he" ? "rtl" : "ltr");
    await noOverflow(page);
    await page.screenshot({ path: `${SHOTS}/${locale}-public-404.png`, fullPage: true });
    expect(problems, problems.join("\n")).toEqual([]);
  });
}
