import { writeFileSync } from "node:fs";

import { chromium, expect, test, type Browser, type Page } from "@playwright/test";

/**
 * Browser load — all modules live (ADR-034). Real Chromium contexts in parallel, each a signed-in
 * person looping the critical circuit: Dashboard → Inbox → /erp (two period switches) →
 * Policies → Reports. The suite fails if any step times out, any core /api XHR answers 5xx, any
 * pageerror fires, or the old phase-gate copy («غير مفعّلة بعد» / «تشغيل هذه المرحلة» /
 * "not enabled yet") renders anywhere. Numbers land in LOAD_REPORT_OUT as JSON — the perf
 * report quotes that file, nothing is typed by hand.
 *
 * Env: LOAD_WEB_URL (default http://127.0.0.1:5176), LOAD_USERS (10), LOAD_CYCLES (3),
 * LOAD_CHROMIUM_EXE (optional executable path), LOAD_REPORT_OUT (/tmp/browser-load-all-live.json).
 */
const BASE = process.env.LOAD_WEB_URL ?? `http://127.0.0.1:${process.env.E2E_WEB_PORT ?? "5176"}`;
const USERS = Number(process.env.LOAD_USERS ?? "10");
const CYCLES = Number(process.env.LOAD_CYCLES ?? "3");
const OUT = process.env.LOAD_REPORT_OUT ?? "/tmp/browser-load-all-live.json";
const PASSWORD = "Br0kerHub!2026";
const GATE_TEXT = /غير مفعّلة بعد|تشغيل هذه المرحلة|المرحلة الثانية|not enabled yet|Enable this phase/i;

type StepStat = { user: string; step: string; ms: number; ok: boolean; detail?: string };
type UserResult = {
  email: string;
  steps: StepStat[];
  server5xx: string[];
  pageerrors: string[];
  gateHits: string[];
};

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.getByLabel(/البريد الإلكتروني/).first().fill(email);
  await page.getByLabel(/كلمة المرور/).first().fill(PASSWORD);
  await page.getByRole("button", { name: "تسجيل الدخول" }).first().click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 45_000 });
}

async function step(user: string, name: string, run: () => Promise<void>): Promise<StepStat> {
  const started = Date.now();
  try {
    await run();
    return { user, step: name, ms: Date.now() - started, ok: true };
  } catch (error) {
    return { user, step: name, ms: Date.now() - started, ok: false, detail: (error as Error).message.split("\n")[0] };
  }
}

async function gotoScreen(page: Page, pathname: string, marker: RegExp): Promise<void> {
  await page.goto(`${BASE}${pathname}`, { waitUntil: "domcontentloaded", timeout: 45_000 });
  await expect(page.locator("main").getByText(marker).first()).toBeVisible({ timeout: 20_000 });
}

type Mode = boolean | "rep";

async function runUser(browser: Browser, email: string, full: Mode): Promise<UserResult> {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ar-EG" });
  const page = await context.newPage();
  const result: UserResult = { email, steps: [], server5xx: [], pageerrors: [], gateHits: [] };
  page.on("pageerror", (error) => result.pageerrors.push(String(error).slice(0, 200)));
  page.on("response", (response) => {
    if (response.status() >= 500 && new URL(response.url()).pathname.startsWith("/api/")) {
      result.server5xx.push(`${response.status()} ${new URL(response.url()).pathname}`);
    }
  });
  try {
    await signIn(page, email);
    for (let cycle = 0; cycle < CYCLES; cycle += 1) {
      // CS has no dashboard screen by RBAC — its circuit is the inbox it actually works.
      if (full === true) {
        result.steps.push(await step(email, "dashboard", () => gotoScreen(page, "/dashboard", /لوحة التحكم/)));
      }
      if (full !== "rep") {
        result.steps.push(await step(email, "inbox", () => gotoScreen(page, "/inbox", /صندوق الطلبات/)));
      }
      if (full === true) {
        result.steps.push(
          await step(email, "erp-periods", async () => {
            await gotoScreen(page, "/erp", /ERP المحاسبي/);
            await page.locator("main").getByRole("button", { name: "ربع سنوي" }).first().click();
            await page.waitForTimeout(600);
            await page.locator("main").getByRole("button", { name: "شهري" }).first().click();
            await page.waitForTimeout(600);
          }),
        );
        result.steps.push(await step(email, "policies-live", () => gotoScreen(page, "/policies", /الوثائق والأقساط/)));
        result.steps.push(await step(email, "reports-live", () => gotoScreen(page, "/reports", /التقارير/)));
        result.steps.push(await step(email, "issuing-live", () => gotoScreen(page, "/issuing", /حالات الإصدار/)));
      }
      if (full === "rep") {
        result.steps.push(await step(email, "leads-kanban", () => gotoScreen(page, "/leads", /ليدز/)));
      }
      const bodyText = await page.locator("body").innerText();
      if (GATE_TEXT.test(bodyText)) result.gateHits.push(`${email} cycle ${cycle}`);
    }
  } catch (error) {
    result.pageerrors.push(`fatal: ${(error as Error).message.split("\n")[0]}`);
  } finally {
    await context.close().catch(() => undefined);
  }
  return result;
}

test("browser load — critical circuit, all modules live, no phase gate anywhere", async ({}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one viewport is enough for a load circuit");
  test.setTimeout(15 * 60_000);
  const browser = await chromium.launch(
    process.env.LOAD_CHROMIUM_EXE ? { executablePath: process.env.LOAD_CHROMIUM_EXE, args: ["--no-sandbox"] } : {},
  );
  // One distinct account per context: two contexts sharing one account rotate each other's
  // refresh token away (the S3 lesson), which reads as random step timeouts, not load.
  const ALL: { email: string; full: Mode }[] = [
    { email: "manager@brokerhub.test", full: true },
    { email: "admin@brokerhub.test", full: true },
    { email: "am@brokerhub.test", full: true },
    { email: "cs@brokerhub.test", full: false },
    { email: "sara.elsayed@brokerhub.test", full: "rep" },
    { email: "mostafa.adel@brokerhub.test", full: "rep" },
    { email: "nour.fahmy@brokerhub.test", full: "rep" },
    { email: "karim.hassan@brokerhub.test", full: "rep" },
  ];
  const plan = ALL.slice(0, Math.min(USERS, ALL.length));
  const started = Date.now();
  const results = await Promise.all(plan.map((u) => runUser(browser, u.email, u.full)));
  await browser.close();

  const steps = results.flatMap((r) => r.steps);
  const failed = steps.filter((s) => !s.ok);
  const byStep: Record<string, { n: number; failed: number; p95: number }> = {};
  for (const name of [...new Set(steps.map((s) => s.step))]) {
    const mine = steps.filter((s) => s.step === name).sort((a, b) => a.ms - b.ms);
    byStep[name] = { n: mine.length, failed: mine.filter((s) => !s.ok).length, p95: mine[Math.floor(0.95 * (mine.length - 1))]?.ms ?? 0 };
  }
  const report = {
    scenario: "browser load — all live (ADR-034)",
    web_url: BASE,
    users: plan.length,
    cycles_per_user: CYCLES,
    duration_s: Math.round((Date.now() - started) / 1000),
    steps: steps.length,
    steps_failed: failed.length,
    failed_detail: failed.slice(0, 10),
    server_5xx: results.flatMap((r) => r.server5xx),
    pageerrors: results.flatMap((r) => r.pageerrors),
    gate_hits: results.flatMap((r) => r.gateHits),
    by_step: byStep,
  };
  writeFileSync(OUT, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));

  expect(report.server_5xx, "core API 5xx during browser load").toEqual([]);
  expect(report.pageerrors, "uncaught page errors").toEqual([]);
  expect(report.gate_hits, "phase-gate copy rendered").toEqual([]);
  expect(failed, "failed steps").toEqual([]);
});
