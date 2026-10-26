import { expect, test, type Page } from "@playwright/test";

import { apiLogin, login, MANAGER, OWNER } from "./fixtures";

/**
 * Every screen of spec §9 must render its own heading and survive a reload without an uncaught
 * exception. This is the cheap suite that catches a broken import or a wrong field name on a screen
 * nobody clicked in a feature test.
 */
type Screen = { route: string; heading: RegExp; who?: "manager" | "rep" | "owner"; phase2?: boolean };

const SCREENS: Screen[] = [
  { route: "/login", heading: /وسيط · Broker Hub|Broker Hub|لوحة تحكم الوسيط/, who: "rep" },
  { route: "/dashboard", heading: /لوحة التحكم/ },
  { route: "/inbox", heading: /صندوق الطلبات الموحد/ },
  { route: "/leads", heading: /لوحة مبيعات|الـLeads/ },
  { route: "/leads/new", heading: /ليد جديد/ },
  { route: "/sales-team", heading: /فريق المبيعات|حِمل/ },
  { route: "/clients", heading: /العملاء/ },
  { route: "/users", heading: /المستخدمون|الأدوار/, who: "manager" },
  { route: "/policies", heading: /الوثائق والأقساط/, phase2: true },
  { route: "/issuing", heading: /حالات الإصدار/, phase2: true },
  { route: "/reports", heading: /التقارير/, phase2: true },
  { route: "/portal", heading: /بوابة العميل/, who: "owner" },
];

async function open(page: Page, screen: Screen) {
  if (screen.route === "/login") {
    await page.goto("/login");
    return;
  }
  await login(page, screen.who === "owner" ? OWNER : MANAGER);
  await page.goto(screen.route);
}

test.describe("screen grid (spec §9)", () => {
  test("the Phase-2 screens stay gated until the flag is on", async ({ page, request }) => {
    const auth = await apiLogin(request, "admin@brokerhub.test");
    const before = await request.patch("/api/v1/feature-flags/phase2.enabled", { headers: auth, data: { enabled: false } });
    expect(before.status(), await before.text()).toBe(200);

    await login(page, MANAGER);
    await page.goto("/policies");
    await expect(page.getByText(/غير مفعّلة بعد/)).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("table tbody tr")).toHaveCount(0);

    const after = await request.patch("/api/v1/feature-flags/phase2.enabled", { headers: auth, data: { enabled: true } });
    expect(after.status()).toBe(200);
    await page.reload();
    await expect(page.getByRole("heading", { name: /الوثائق والأقساط/ })).toBeVisible({ timeout: 20_000 });
  });

  for (const screen of SCREENS) {
    test(`${screen.route} renders without an uncaught error`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await open(page, screen);
      await expect(page.getByText(screen.heading).first()).toBeVisible({ timeout: 20_000 });
      await expect.poll(() => errors, { timeout: 5_000 }).toHaveLength(0);
    });
  }

  test("the client file, insured roster and lead detail open by id", async ({ page, request }) => {
    const auth = await apiLogin(request, MANAGER);
    const clientId = (await (await request.get("/api/v1/clients?limit=1", { headers: auth })).json()).items[0].id as string;
    const leadId = (await (await request.get("/api/v1/leads?limit=1", { headers: auth })).json()).items[0].id as string;

    await login(page, MANAGER);
    await page.goto(`/clients/${clientId}`);
    await expect(page.getByText(/ملف العميل|معلومات الوثيقة/).first()).toBeVisible({ timeout: 20_000 });

    await page.goto(`/clients/${clientId}/insured`);
    await expect(page.getByRole("heading", { name: /الموظفون المؤمَّن عليهم/ })).toBeVisible();

    await page.goto(`/leads/${leadId}`);
    await expect(page.getByText(/تفاصيل الـLead|مسار البيع|جديد/).first()).toBeVisible({ timeout: 20_000 });
  });
});
