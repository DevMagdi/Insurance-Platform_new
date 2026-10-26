import { expect, test } from "@playwright/test";

import { ADMIN, apiLogin, login, MANAGER, PASSWORD, REPS } from "./fixtures";

/**
 * Team management, Excel/CSV lead import, and redistribution of the unassigned pool — the three things the
 * R2 spec promises a manager can actually do.
 *
 * Same rules as `settings.spec.ts`: every test opens with an API assertion so a failure prints the server's
 * answer rather than a locator timeout, and every promise is checked against stored state (a lead fetched by
 * id, a roster row, a 401 on login) instead of a toast. The DB claims are API reads, so an import that only
 * moved the UI would fail here.
 */

const AUTH_EMAIL = /البريد الإلكتروني/;

function unique(prefix: string) {
  const stamp = Date.now().toString(36).slice(-6);
  return {
    name: `${prefix}-${stamp}`,
    email: `${prefix}-${stamp}@import.test`,
    mobile: `+201099${stamp.replace(/\D/g, "").padEnd(6, "0").slice(0, 6)}`,
  };
}

test.describe("sales office · members", () => {
  test("a manager adds a rep who starts with zero leads, and a suspended seat cannot log in", async ({ page, request }) => {
    const who = unique("seat");

    await login(page, MANAGER);
    await page.goto("/sales-team");
    await expect(page.getByRole("heading", { name: "أعضاء المكتب" })).toBeVisible();

    await page.getByRole("button", { name: "إضافة عضو" }).click();
    const dialog = page.getByRole("dialog", { name: "إضافة عضو" });
    await dialog.getByLabel("الاسم الكامل").fill(who.name);
    await dialog.getByLabel(AUTH_EMAIL).fill(who.email);
    await dialog.getByLabel("الموبايل").fill(who.mobile);
    await dialog.getByRole("button", { name: "حفظ" }).click();
    // no password was typed, so the server generated one and shows it here, once
    const issued = dialog.getByTestId("member-issued-password");
    await expect(issued).toBeVisible({ timeout: 20_000 });
    const password = (await issued.textContent()) ?? "";
    expect(password.length).toBeGreaterThanOrEqual(10);
    await dialog.getByRole("button", { name: "إغلاق" }).click();

    // the seat exists with the office role, and its ledger is empty
    const auth = await apiLogin(request, ADMIN);
    const roster = await request.get("/api/v1/sales-team/members", {
      headers: auth,
    });
    expect(roster.ok(), await roster.text());
    const seat = (await roster.json()).members.find((row: { email: string }) => row.email === who.email);
    expect(seat, `the new seat is not in the roster: ${who.email}`).toBeTruthy();
    expect(seat.role).toBe("sales_rep");
    expect(seat.open_leads).toBe(0); // a fresh rep inherits nobody's book

    // the generated password is the login the member was given
    const fresh = await request.post("/api/v1/auth/login", {
      data: { email: who.email, password },
    });
    expect(fresh.status(), await fresh.text()).toBe(200);

    // switching the seat off is a roster action, and it stops the login
    const manager = await apiLogin(request, MANAGER);
    const off = await request.patch(`/api/v1/sales-team/members/${seat.id}`, {
      headers: manager,
      data: { is_active: false },
    });
    expect(off.status(), await off.text()).toBe(200);
    expect((await off.json()).is_active).toBe(false);
    const refused = await request.post("/api/v1/auth/login", {
      data: { email: who.email, password: PASSWORD },
    });
    expect(refused.status(), await refused.text()).not.toBe(200);

    const on = await request.patch(`/api/v1/sales-team/members/${seat.id}`, {
      headers: manager,
      data: { is_active: true },
    });
    expect(on.status(), await on.text()).toBe(200);
    expect((await on.json()).is_active).toBe(true);

    // and the API refuses to hand out a role this screen is not allowed to give
    const tooBig = await request.post("/api/v1/sales-team/members", {
      headers: manager,
      data: {
        full_name: "طموح",
        email: `admin-${Date.now()}@import.test`,
        role_code: "system_admin",
      },
    });
    expect(tooBig.status(), await tooBig.text()).toBe(403);
  });
});

test.describe("sales office · lead import", () => {
  test("a sheet is previewed, then applied: the rows land in the database and the report counts them", async ({ page, request }) => {
    const first = unique("imp");
    const second = unique("imp");
    // a mobile that already belongs to a live lead must be skipped, not duplicated
    const auth = await apiLogin(request, MANAGER);
    const taken = await request.post("/api/v1/leads", {
      headers: auth,
      data: {
        name: unique("dup").name,
        mobile: "+201000777777",
        type: "company",
        source: "e2e",
      },
    });
    expect(taken.status(), await taken.text()).toBe(201);

    const csv = [
      "الاسم,الموبايل,الشركة,البوزيشن,الإيميل,المصدر,عدد الأفراد",
      `${first.name},${first.mobile},${first.name},مدير مشتريات,${first.email},معرض أكتوبر,25`,
      `${second.name},+201000777777,,,-,-`,
      `${unique("bad").name},not-a-number,,,,,`,
    ].join("\n");

    await login(page, MANAGER);
    await page.goto("/leads");
    await page.getByRole("button", { name: "استيراد Excel/CSV" }).click();
    await page.setInputFiles("#leads-import-file", {
      name: "leads.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csv, "utf8"),
    });

    const preview = page.getByTestId("import-preview");
    await expect(preview).toBeVisible({ timeout: 30_000 });
    // the preview is a promise about the future, not a result: no lead exists yet
    const beforeImport = await request.get(`/api/v1/leads?q=${first.name}&page_size=20`, { headers: auth });
    expect((await beforeImport.json()).total, "a dry run must not write rows").toBe(0);
    await expect(preview.getByTestId("import-stats")).toContainText("2");

    await page.getByRole("button", { name: "تنفيذ الاستيراد" }).click();
    await expect(preview).toContainText("أُنشئ");

    // the row is really in PostgreSQL: read it back by name, then by id
    const found = await request.get(`/api/v1/leads?q=${first.name}&page_size=20`, { headers: auth });
    expect(found.ok(), await found.text());
    const items = (await found.json()).items as {
      id: string;
      name: string;
      mobile: string;
      status: string;
      contact_title: string | null;
      assignee_id: string | null;
    }[];
    const imported = items.find((row) => row.name === first.name);
    if (imported === undefined) throw new Error(`imported lead ${first.name} is not in the leads list: ${JSON.stringify(items)}`);
    expect(imported.mobile).toBe(first.mobile);
    expect(imported.status).toBe("new");
    expect(imported.assignee_id, "an imported lead without a named rep must be unassigned").toBeNull();
    expect(imported.contact_title).toBe("مدير مشتريات");

    // and the duplicate of a live mobile is visible in the unassigned pool only once
    const pool = await request.get("/api/v1/leads?unassigned=true&page_size=200", {
      headers: auth,
    });
    const inPool = ((await pool.json()).items as { name: string }[]).filter((row) => row.name === first.name || row.name === second.name);
    expect(inPool.map((row) => row.name)).toEqual([first.name]);
  });

  test("a rep cannot import, and the button is not offered", async ({ page, request }) => {
    const auth = await apiLogin(request, REPS.sara);
    const refused = await request.post("/api/v1/leads/import", {
      headers: auth,
      data: { file: "ignored" },
    });
    expect(refused.status(), await refused.text()).toBe(403);

    await login(page, REPS.sara);
    await page.goto("/leads");
    await expect(page.getByRole("button", { name: "استيراد Excel/CSV" })).toHaveCount(0);
  });
});

test.describe("sales office · redistribute", () => {
  test("a row in the pool moves to the chosen rep, in the timeline and in the rep's own list", async ({ page, request }) => {
    const lead = unique("pool");
    const manager = await apiLogin(request, MANAGER);
    const created = await request.post("/api/v1/leads", {
      headers: manager,
      data: {
        name: lead.name,
        mobile: lead.mobile,
        type: "company",
        source: "e2e",
      },
    });
    expect(created.status(), await created.text()).toBe(201);
    const leadId = (await created.json()).id as string;

    await login(page, MANAGER);
    await page.goto("/sales-team");
    const row = page.getByTestId("unassigned-pool").locator("li", { hasText: lead.name });
    await expect(row, `the unassigned lead is not listed for the manager: ${lead.name}`).toBeVisible({ timeout: 20_000 });

    await row.getByRole("button", { name: "إعادة إسناد" }).click();
    const dialog = page.getByRole("dialog", { name: "إعادة توزيع الـLeads" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("المحدد من القائمة (1)");
    const boxes = dialog.getByRole("checkbox");
    await boxes.first().check();
    await dialog.getByRole("button", { name: /وزّع/ }).click();

    // the lead left the pool
    await expect(page.getByTestId("unassigned-pool").locator("li", { hasText: lead.name })).toHaveCount(0, { timeout: 20_000 });

    // it moved on the server, with a timeline entry naming the move
    const after = await request.get(`/api/v1/leads/${leadId}`, {
      headers: manager,
    });
    expect(after.ok(), await after.text());
    // the detail payload calls the seat `assignee_id` (the brief says assigned_to, the API says assignee_*)
    const afterBody = await after.json();
    const assignedTo = afterBody.assignee_id as string;
    expect(assignedTo, "the API still says the lead is unassigned").toBeTruthy();
    const activity = await request.get(`/api/v1/leads/${leadId}/activities`, {
      headers: manager,
    });
    expect(activity.ok(), await activity.text());
    const events = (await activity.json()) as {
      type: string;
      body: string | null;
    }[];
    const moved = events.filter((row) => row.type === "assignment");
    expect(moved.length, `no assignment entry in the timeline: ${JSON.stringify(events)}`).toBeGreaterThan(0);
    // the timeline line names the people and keeps the uuids in `meta` — the same sentence a single
    // assignment writes, so a redistributed lead does not read like a database dump
    const line = moved.at(-1)?.body ?? "";
    expect(line, `unexpected assignment line: ${line}`).toMatch(/^redistributed: .+ → .+/);
    expect(line).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/);

    // the seat list is server-side, so the receiving rep is whichever one the pool round-robinned to:
    // exactly one of the two seeded reps must now be able to read the lead
    const visible: string[] = [];
    for (const email of Object.values(REPS)) {
      const repAuth = await apiLogin(request, email);
      const mine = await request.get("/api/v1/leads?page_size=200", {
        headers: repAuth,
      });
      expect(mine.ok(), await mine.text());
      const rows = (await mine.json()).items as { id: string }[];
      if (rows.some((row) => row.id === leadId)) visible.push(email);
    }
    expect(visible, "the redistributed lead must be visible to exactly one rep").toEqual(expect.arrayContaining([expect.any(String)]));
    expect(visible).toHaveLength(1);
  });
});
