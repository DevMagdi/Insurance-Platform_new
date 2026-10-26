import { expect, test } from "@playwright/test";

import { ar } from "../src/lib/i18n/ar";

import { apiLogin, CS, login, MANAGER, OWNER, REPS } from "./fixtures";

/**
 * The isolation rule the product lives or dies by (spec §6): what a rep cannot see must be invisible
 * in the UI *and* unreachable through the API, with the by-id case answering 404 — never 403.
 * Copy is read from the dictionary, so a wording change here means a real product change.
 */
test.describe("sales kanban + isolation (screens 3, 6, 9)", () => {
  test("a rep sees only their own leads, with the isolation banner", async ({ page, request }) => {
    await login(page, REPS.sara);
    await page.goto("/leads");

    await expect(page.getByText(ar.leads.isolationBanner)).toBeVisible();

    const auth = await apiLogin(request, REPS.sara);
    const mine = await (await request.get("/api/v1/leads?limit=100", { headers: auth })).json();
    const mineIds = new Set<string>(mine.items.map((lead: { id: string }) => lead.id));
    await expect(page.locator("[data-lead-card]")).toHaveCount(mine.items.length, { timeout: 15_000 });

    const managerAuth = await apiLogin(request, MANAGER);
    const all = await (await request.get("/api/v1/leads?limit=100", { headers: managerAuth })).json();
    const foreign = all.items.find((lead: { id: string }) => !mineIds.has(lead.id));
    expect(foreign, "the seed must contain another rep's lead for this test to mean anything").toBeTruthy();

    await expect(page.locator(`[data-lead-card="${foreign.id}"]`)).toHaveCount(0);
    expect((await request.get(`/api/v1/leads/${foreign.id}`, { headers: auth })).status()).toBe(404);
    expect((await request.patch(`/api/v1/leads/${foreign.id}`, { data: { status: "lost" }, headers: auth })).status()).toBe(404);
    expect((await request.get(`/api/v1/leads/${foreign.id}/activities`, { headers: auth })).status()).toBe(404);

    // KPI counts follow the same scope
    const stats = await (await request.get("/api/v1/leads/stats", { headers: auth })).json();
    expect(stats.my_leads).toBe(mine.total);
  });

  test("a manager sees the whole office and every stage column", async ({ page, request }) => {
    await login(page, MANAGER);
    await page.goto("/leads");
    for (const column of [ar.leads.colNew, ar.leads.colContacted, ar.leads.colMeeting, ar.leads.colQuote, ar.leads.colWon]) {
      await expect(page.getByText(column, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText(ar.leads.isolationBanner)).toHaveCount(0);

    const auth = await apiLogin(request, MANAGER);
    const total = (await (await request.get("/api/v1/leads?limit=1", { headers: auth })).json()).total as number;
    await expect(page.locator("[data-lead-card]")).toHaveCount(total, { timeout: 15_000 });
  });

  test("converting a lead creates the client file and lands on it", async ({ page, request }) => {
    test.slow();
    await login(page, MANAGER);
    const auth = await apiLogin(request, MANAGER);

    const created = await request.post("/api/v1/leads", {
      headers: auth,
      data: {
        source: "whatsapp",
        contact_name: "منى فؤاد — قسم الموارد البشرية",
        company_name: "شركة منطق للملابس الجاهزة",
        mobile: `+201100${String(Date.now()).slice(-6)}`,
        subject: "تأمين طبي لعمالة موسمية",
        insurance_type: "medical",
        note: "عدد العمالة المتوقع 450 فردًا",
      },
    });
    expect(created.status(), await created.text()).toBe(201);
    const lead = await created.json();

    await page.goto("/leads");
    await expect(page.locator(`[data-lead-card="${lead.id}"]`)).toBeVisible({ timeout: 15_000 });

    // the conversion happens from the lead detail, behind a two-step confirm — never a drag-only gesture
    await page.goto(`/leads/${lead.id}`);
    await page.getByRole("button", { name: ar.leads.convertCta }).click();
    await expect(page.getByText(ar.leads.confirmWon)).toBeVisible();
    await page.getByRole("button", { name: ar.leads.convert, exact: true }).click();

    await expect(page.getByText(ar.leads.convertDone)).toBeVisible({ timeout: 20_000 });
    await expect(page).toHaveURL(/\/clients\//, { timeout: 20_000 });

    const clientId = new URL(page.url()).pathname.split("/clients/")[1] ?? "";
    expect(clientId).toBeTruthy();
    const client = await (await request.get(`/api/v1/clients/${clientId}`, { headers: auth })).json();
    expect(client.name).toContain("منطق");
    // the green banner on the clients list is the designer's confirmation this came from a lead
    await page.goto("/clients");
    await expect(page.getByText(/تم تحويله من Lead إلى عميل فعلي/)).toBeVisible();
  });

  test("the mobile board renders the same queue at 390×844", async ({ page, request }) => {
    test.skip(test.info().project.name !== "mobile", "mobile project only");
    await login(page, REPS.sara);
    await page.goto("/mobile/leads");
    await expect(page.getByText(ar.leads.mobile.seeOnlyYours)).toBeVisible();

    const auth = await apiLogin(request, REPS.sara);
    const total = (await (await request.get("/api/v1/leads?limit=1", { headers: auth })).json()).total as number;
    if (total > 0) {
      await expect(page.locator("[data-lead-card]").first()).toBeVisible({ timeout: 15_000 });
    }
    await expect(page.getByRole("button", { name: ar.leads.newLead, exact: true })).toBeVisible();
  });
});

test.describe("portal privacy (screens 7, 15)", () => {
  test("the client owner lands on the portal shell, not the staff shell", async ({ page }) => {
    await login(page, OWNER);
    await expect(page).toHaveURL(/\/portal/);
    expect(page.url()).not.toContain("/dashboard");
    await expect(page.getByText(ar.portal.brand)).toBeVisible();

    // staff-only vocabulary must not appear anywhere in the portal DOM
    for (const label of [ar.inbox.internalNote, ar.clients.colOwner, "تسجيلات", ar.dashboard.colChannel]) {
      await expect(page.getByText(label, { exact: true })).toHaveCount(0);
    }
  });

  test("a portal token cannot read staff endpoints at all", async ({ request }) => {
    const headers = await apiLogin(request, OWNER);
    for (const path of ["/api/v1/requests", "/api/v1/leads", "/api/v1/clients", "/api/v1/users", "/api/v1/audit"]) {
      const response = await request.get(path, { headers });
      expect([401, 403, 404], `${path} → ${response.status()}`).toContain(response.status());
    }
  });

  test("customer service works the queue but not the sales board", async ({ page, request }) => {
    await login(page, CS);
    await page.goto("/inbox");
    await expect(page.locator("[data-request-row]").first()).toBeVisible({ timeout: 15_000 });
    const auth = await apiLogin(request, CS);
    expect((await request.get("/api/v1/leads", { headers: auth })).status()).toBe(403);
    expect((await request.get("/api/v1/clients", { headers: auth })).status()).toBe(403);
  });
});
