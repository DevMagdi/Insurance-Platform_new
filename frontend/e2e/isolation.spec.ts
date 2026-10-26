import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { ar } from "../src/lib/i18n/ar";

import { apiLogin, CS, login, MANAGER, OWNER, REPS } from "./fixtures";

/**
 * The isolation rule the product lives or dies by (spec §6): what a rep cannot see must be invisible
 * in the UI *and* unreachable through the API, with the by-id case answering 404 — never 403.
 * Copy is read from the dictionary, so a wording change here means a real product change.
 *
 * The board is compared against `GET /leads/board`, not against `/leads` total: screen 3 shows five
 * columns (`new…won`, see `LeadStatus.board_columns()`) and `lost`/`postponed` are reachable only through
 * filters. Counting cards against the whole list asked the board to display rows it deliberately does not
 * show — the first CI run on this branch failed on exactly that, and the honest fix is to compare a screen
 * with the payload that screen is defined by, then assert the isolation on the ids themselves.
 */

/** The ids currently rendered on the board, as the DOM says them. */
async function cardIds(page: Page): Promise<string[]> {
  return page.locator("[data-lead-card]").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-lead-card") ?? ""));
}

/** `{id, count}` per column straight from the API, so the assertion is the server's own definition. */
async function boardOf(request: APIRequestContext, headers: Record<string, string>) {
  const response = await request.get("/api/v1/leads/board", { headers });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  const ids: string[] = body.columns.flatMap((column: { items: { id: string }[] }) => column.items.map((row: { id: string }) => row.id));
  const counts: number[] = body.columns.map((column: { count: number }) => column.count);
  return { ids, counts, total: ids.length };
}

test.describe("sales kanban + isolation (screens 3, 6, 9)", () => {
  test("a rep sees only their own leads, with the isolation banner", async ({ page, request }) => {
    await login(page, REPS.sara);
    await page.goto("/leads");

    await expect(page.getByText(ar.leads.isolationBanner)).toBeVisible();

    const auth = await apiLogin(request, REPS.sara);
    const mine = await (await request.get("/api/v1/leads?page_size=100", { headers: auth })).json();
    const mineIds = new Set<string>(mine.items.map((lead: { id: string }) => lead.id));
    const board = await boardOf(request, auth);

    await expect(page.locator("[data-lead-card]")).toHaveCount(board.total, { timeout: 15_000 });
    const shown = await cardIds(page);
    expect(new Set(shown), "the board must render exactly the payload the scoped endpoint returned").toEqual(new Set(board.ids));
    // the isolation claim itself: nothing on this rep's board belongs to somebody else
    expect(shown.filter((id) => !mineIds.has(id)), "a foreign lead appeared on the rep's board").toEqual([]);

    const managerAuth = await apiLogin(request, MANAGER);
    const all = await (await request.get("/api/v1/leads?page_size=100", { headers: managerAuth })).json();
    const foreign = all.items.find((lead: { id: string }) => !mineIds.has(lead.id));
    expect(foreign, "the seed must contain another rep's lead for this test to mean anything").toBeTruthy();

    await expect(page.locator(`[data-lead-card="${foreign.id}"]`)).toHaveCount(0);
    expect((await request.get(`/api/v1/leads/${foreign.id}`, { headers: auth })).status()).toBe(404);
    expect((await request.patch(`/api/v1/leads/${foreign.id}`, { data: { status: "lost" }, headers: auth })).status()).toBe(404);
    expect((await request.get(`/api/v1/leads/${foreign.id}/activities`, { headers: auth })).status()).toBe(404);

    // KPI counts follow the same scope: `my_leads` is the active set (won/lost out), measured on the same rows
    const stats = await (await request.get("/api/v1/leads/stats", { headers: auth })).json();
    const activeMine = mine.items.filter((lead: { status: string }) => lead.status !== "won" && lead.status !== "lost").length;
    expect(stats.my_leads, "the KPI and the scoped list must agree about what is mine").toBe(activeMine);
  });

  test("a manager sees the whole office and every stage column", async ({ page, request }) => {
    await login(page, MANAGER);
    await page.goto("/leads");
    for (const column of [ar.leads.colNew, ar.leads.colContacted, ar.leads.colMeeting, ar.leads.colQuote, ar.leads.colWon]) {
      await expect(page.getByText(column, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText(ar.leads.isolationBanner)).toHaveCount(0);

    const auth = await apiLogin(request, MANAGER);
    const board = await boardOf(request, auth);
    await expect(page.locator("[data-lead-card]")).toHaveCount(board.total, { timeout: 15_000 });
    expect(board.counts).toHaveLength(5);

    // the point of the manager view is more than one owner on the same board
    const rows = (await (await request.get("/api/v1/leads?page_size=100", { headers: auth })).json()).items as {
      id: string;
      assigned_to: string | null;
    }[];
    const owners = new Set(rows.map((row) => row.assigned_to).filter((id): id is string => Boolean(id)));
    expect(owners.size, "a manager's board must span the office, not one seat").toBeGreaterThan(1);
    // the same rule as the rep's test, in the other direction: the manager's board holds the office's rows
    const officeIds = new Set(rows.map((row) => row.id));
    const shown = await cardIds(page);
    expect(shown.filter((id) => !officeIds.has(id)), "the manager's board shows leads the list does not").toEqual([]);
  });

  test("converting a lead creates the client file and lands on it", async ({ page, request }) => {
    test.slow();
    await login(page, MANAGER);
    const auth = await apiLogin(request, MANAGER);

    const created = await request.post("/api/v1/leads", {
      headers: auth,
      // `LeadCreate` is the contract: name/contact/mobile/source/needs_text — an intake-shaped payload is a 422
      data: {
        type: "company",
        name: "شركة منطق للملابس الجاهزة",
        contact_name: "منى فؤاد",
        contact_title: "مسؤول الموارد البشرية",
        mobile: `+201100${String(Date.now()).slice(-6)}`,
        email: "mona@manteq.test",
        source: "whatsapp",
        headcount: 450,
        needs_text: "تأمين طبي لعمالة موسمية · عدد العمالة المتوقع 450 فردًا",
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
    const total = (await (await request.get("/api/v1/leads?page_size=1", { headers: auth })).json()).total as number;
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
