import { expect, test } from "@playwright/test";

import { formatNumber } from "../src/lib/format";

import { apiLogin, login, MANAGER, REPS } from "./fixtures";

/** Screen 1 — the daily cockpit, plus the shell rules (RTL, sidebar, real numbers only). */
test.describe("dashboard (screen 1)", () => {
  test("renders the four KPIs from the API and no placeholder numbers", async ({ page, request }) => {
    const auth = await apiLogin(request, MANAGER);
    const summary = await (await request.get("/api/v1/dashboard/summary", { headers: auth })).json();

    await login(page, MANAGER);
    await expect(page.getByRole("heading", { name: "لوحة التحكم", exact: true })).toBeVisible();
    await expect(page.getByText("نظرة حية على كل الطلبات والقنوات")).toBeVisible();

    for (const label of ["طلبات اليوم", "متوسط زمن أول رد", "الالتزام بالـSLA", "طلبات متأخرة"]) {
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }

    // the KPI tiles must carry the API's numbers (Egyptian digits), never the mockup's hardcoded ones
    const main = await page.locator("main").innerText();
    expect(main).not.toMatch(/TBD|lorem/i);
    expect(main).toContain(formatNumber(summary.requests_today));
    if (summary.sla_compliance_pct !== null && summary.sla_compliance_pct !== undefined) {
      expect(main, "percentages must be localised").toContain("٪");
    }

    // charts and the recent table are real content, not skeletons
    await expect(page.getByText("الطلبات حسب القناة — آخر 7 أيام")).toBeVisible();
    await expect(page.getByText("أحدث الطلبات")).toBeVisible();
    await expect(page.locator('[data-request-row], table tbody tr').first()).toBeVisible({ timeout: 15_000 });
  });

  test("the shell is RTL with the sidebar nav on the logical start edge", async ({ page }) => {
    await login(page, MANAGER);
    const root = page.locator("html");
    await expect(root).toHaveAttribute("dir", "rtl");
    await expect(root).toHaveAttribute("lang", "ar");

    const nav = page.getByRole("navigation", { name: /التنقل|primary/i });
    await expect(nav).toBeVisible();
    const box = await nav.boundingBox();
    const viewport = page.viewportSize();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThan((viewport?.width ?? 1440) / 2); // RTL ⇒ sidebar sits on the right

    for (const item of ["صندوق الطلبات", "العملاء"]) {
      await expect(nav.getByText(item, { exact: true }).first()).toBeVisible();
    }
    await expect(page.locator("body")).toHaveCSS("background-color", "rgb(243, 244, 249)");
  });

  test("the header search filters the shared queue", async ({ page }) => {
    await login(page, MANAGER);
    const box = page.getByRole("search").getByRole("textbox");
    await box.fill("أحمد");
    await box.press("Enter");
    await expect(page).toHaveURL(/\?q=/);
    await expect(page.getByRole("heading", { name: "صندوق الطلبات الموحد", exact: true })).toBeVisible({ timeout: 20_000 });
  });

  test("a rep is redirected into their own queue", async ({ page, request }) => {
    await login(page, REPS.sara);
    const auth = await apiLogin(request, REPS.sara);
    const mine = await (await request.get("/api/v1/requests?limit=1", { headers: auth })).json();

    await expect(page.getByRole("heading", { name: "صندوق الطلبات الموحد", exact: true })).toBeVisible({ timeout: 20_000 });
    const rows = page.locator("[data-request-row]");
    await expect(rows.first()).toBeVisible();
    if (mine.total === 0) {
      await expect(page.getByText(/لا توجد طلبات مطابقة/)).toBeVisible();
    } else {
      await expect(rows).toHaveCount(Math.min(mine.items.length, 25));
    }
  });
});
