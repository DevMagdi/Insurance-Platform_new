import { existsSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { apiLogin, login, MANAGER } from "./fixtures";

const SHEET = path.resolve(import.meta.dirname, "fixtures/insured.xlsx");
const FAKE = path.resolve(import.meta.dirname, "fixtures/not-excel.csv");

const read = async (file: string) => (await import("node:fs")).readFileSync(file);

/**
 * Screen 11 — the Excel round trip. The sheet must survive upload → dry-run → confirm → report, and a
 * non-workbook must be refused with a 422 instead of a 500 (a real defect this test was written for).
 */
test.describe("insured persons import (screen 11)", () => {
  test.skip(!existsSync(SHEET), "fixture workbook missing");

  test("dry-run shows what would change, then the commit writes the roster", async ({ page, request }) => {
    test.slow();
    const auth = await apiLogin(request, MANAGER);
    const clients = await (await request.get("/api/v1/clients?limit=1", { headers: auth })).json();
    expect(clients.items.length, "the seed must contain at least one client").toBeGreaterThan(0);
    const clientId = clients.items[0].id as string;
    const clientName = clients.items[0].name as string;

    await login(page, MANAGER);
    await page.goto(`/clients/${clientId}/insured`);
    await expect(page.getByRole("heading", { name: /الموظفون المؤمَّن عليهم/ })).toBeVisible();
    await expect(page.getByText(clientName)).toBeVisible();

    const upload = page.locator('input[type="file"]');
    await upload.setInputFiles(SHEET);

    // dry-run: nothing is written yet
    await expect(page.getByText(/لم يُحفظ شيء بعد/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/إضافة/).first()).toBeVisible();
    // `GET /clients/{id}/insured` answers { kpis, page: { items, total } } — read the envelope.
    const rosterTotal = async () => {
      const body = await (await request.get(`/api/v1/clients/${clientId}/insured?limit=1`, { headers: auth })).json();
      return body.page.total as number;
    };
    const before = await rosterTotal();

    await page.getByRole("button", { name: "تأكيد الاستيراد", exact: true }).click();

    await expect(page.getByText(/تقرير النتائج|تم حفظ/).first()).toBeVisible({ timeout: 30_000 });
    const after = await rosterTotal();
    expect(after).toBeGreaterThan(before);

    // and the roster in the UI now lists the imported employee
    await page.reload();
    await expect(page.getByText("منى فؤاد").first()).toBeVisible({ timeout: 20_000 });
  });

  test("a non-xlsx file is refused, and the report separates the bad row", async ({ request }) => {
    const auth = await apiLogin(request, MANAGER);
    const clientId = (await (await request.get("/api/v1/clients?limit=1", { headers: auth })).json()).items[0].id as string;

    const refused = await request.post(`/api/v1/clients/${clientId}/insured/import`, {
      headers: auth,
      multipart: { file: { name: "not-excel.csv", mimeType: "text/csv", buffer: await read(FAKE) } },
    });
    expect(refused.status()).toBe(422);
    const rejection = await refused.json();
    expect(JSON.stringify(rejection)).toContain("xlsx");

    const dry = await request.post(`/api/v1/clients/${clientId}/insured/import`, {
      headers: auth,
      multipart: {
        file: { name: "insured.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: await read(SHEET) },
      },
    });
    expect(dry.status(), await dry.text()).toBe(201);
    const report = await dry.json();
    // the sheet holds 4 rows: two clean inserts, one bad mobile, one duplicate of the first row
    expect(report.total_rows).toBe(4);
    expect(report.stats.rejected).toBe(2);
    expect(report.stats.will_create).toBe(2);
    expect(report.status).toBe("dry_run");
    expect(JSON.stringify(report.error_report)).toContain("mobile");
  });
});
