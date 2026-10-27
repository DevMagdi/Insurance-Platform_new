import { expect, test, type APIRequestContext } from "@playwright/test";

import { ar } from "../src/lib/i18n/ar";

import { apiLogin, ADMIN, login, MANAGER, OWNER } from "./fixtures";

/**
 * R5 — the five paths that used to end at a screen instead of at a result: issuance (a file), the manager's
 * lead filters, portal accounts (a username that signs in) and the portal's own policy download.
 *
 * Every test arranges through the API and then proves the *browser* did the work:
 * - a policy is created by the API and issued by clicking «إصدار» in the table, and the download is a real
 *   Playwright `download` event with a `.pdf` filename (a broken `<a href>` fires nothing);
 * - the filter test compares the cards on screen with the rows the API returns for the same filter, so a
 *   client-side filter that ignored the query string would fail here;
 * - the portal test signs in with a *username* (not the generated mailbox) in a fresh browser context.
 *
 * Desktop only, same rule as `team-round.spec.ts` (ADR-019): the policies table and the client-file dialogs
 * are 1440×900 surfaces from the design sheet, and a phone run would spend the budget chasing a table
 * column that scrolls out of the viewport instead of asserting a fact. The API half of every flow runs on the
 * server and is covered at both widths by `scripts/live_matrix.py`.
 */

function desktopOnly(testInfo: { project: { name: string } }): boolean {
  return testInfo.project.name !== "desktop";
}

let counter = 0;
function unique(prefix: string): string {
  counter += 1;
  return `${prefix}.${Date.now().toString(36)}${counter}`.toLowerCase();
}

async function phase2On(request: APIRequestContext): Promise<void> {
  const auth = await apiLogin(request, ADMIN);
  const response = await request.patch("/api/v1/feature-flags/phase2.enabled", { headers: auth, data: { enabled: true } });
  expect(response.status(), await response.text()).toBe(200);
}

test.describe("R5 · issuance, filters and portal accounts", () => {
  test("a manager issues a draft from the table and downloads the PDF", async ({ page, request }, testInfo) => {
    test.skip(desktopOnly(testInfo), "1440×900 table flow (ADR-019)");
    await phase2On(request);
    const auth = await apiLogin(request, MANAGER);

    // the portal owner's company: the same client the portal test below downloads from
    const ownerAuth = await apiLogin(request, OWNER);
    const ownerClient = (await (await request.get("/api/v1/portal/overview", { headers: ownerAuth })).json()).client.id as string;

    const draft = await request.post("/api/v1/policies", {
      headers: auth,
      data: {
        client_id: ownerClient,
        start_date: "2026-11-01",
        end_date: "2027-10-31",
        premium_amount: 275000,
        headcount: 33,
        notes: `R5 issuance ${unique("qa")}`,
      },
    });
    expect(draft.status(), await draft.text()).toBe(201);
    const policyId = (await draft.json()).id as string;

    await login(page, MANAGER);
    await page.goto("/policies");
    await expect(page.getByRole("heading", { name: /الوثائق والأقساط/ })).toBeVisible({ timeout: 20_000 });

    // the list is newest-first, so the draft this test just created is the first row
    const row = page.locator("table tbody tr").first();
    await expect(row).toBeVisible({ timeout: 20_000 });
    const issue = row.getByRole("button", { name: ar.phase2.issueAction, exact: true });
    await expect(issue).toBeVisible();
    const issued = await request.get(`/api/v1/policies?page_size=5`, { headers: auth });
    expect(issued.ok()).toBeTruthy();

    await issue.click();
    const download = row.getByRole("button", { name: ar.common.download, exact: true });
    await expect(download).toBeVisible({ timeout: 20_000 });

    // the file: a download event with a name that ends in .pdf, and the API agrees a file exists
    const [file] = await Promise.all([page.waitForEvent("download"), download.click()]);
    expect(file.suggestedFilename().toLowerCase()).toMatch(/\.pdf$/);
    const saved = await request.get(`/api/v1/policies/${policyId}/document`, { headers: auth });
    expect(saved.status()).toBe(200);
    expect(saved.headers()["content-type"]).toContain("application/pdf");
    expect((await saved.body()).subarray(0, 5).toString()).toBe("%PDF-");
  });

  test("the Kanban filters by rep, by stage and by the unassigned pool", async ({ page, request }, testInfo) => {
    test.skip(desktopOnly(testInfo), "1440×900 board flow (ADR-019)");
    const auth = await apiLogin(request, MANAGER);

    const team = (await (await request.get("/api/v1/sales/team", { headers: auth })).json()) as { rep_id: string; name: string; open_leads: number }[];
    const rep = team.find((member) => member.open_leads > 0);
    expect(rep, "the seed has a rep with open leads").toBeTruthy();
    const expected = (await (await request.get(`/api/v1/leads?assigned_to=${rep!.rep_id}&page_size=100`, { headers: auth })).json()).items as {
      name: string;
    }[];
    expect(expected.length).toBeGreaterThan(0);

    await login(page, MANAGER);
    await page.goto("/leads");
    await expect(page.getByRole("heading", { name: /ليدز/ })).toBeVisible({ timeout: 20_000 });

    // filter by the rep: the value is the id, because the option label carries a formatted count
    await page.getByLabel(ar.leads.filterRep).selectOption(rep!.rep_id);
    await expect.poll(async () => page.locator("article").count(), { timeout: 20_000 }).toBeGreaterThan(0);
    const cards = await page.locator("article").allTextContents();
    const names = expected.map((lead) => lead.name);
    for (const card of cards) {
      expect(names.some((name) => card.includes(name)), `a card outside ${rep!.name}'s book: ${card.slice(0, 60)}`).toBeTruthy();
    }

    // stage: one lane, and it is the lane that was asked for
    await page.getByLabel(ar.leads.filterStage).selectOption("new");
    await expect(page.locator("[data-column]")).toHaveCount(1);
    await expect(page.locator("[data-column]").first()).toHaveAttribute("data-column", "new");
    await page.getByLabel(ar.leads.filterStage).selectOption("");

    // the pool: rep filter + unassigned is empty on purpose (an unassigned lead has no rep)
    await page.getByLabel(ar.leads.filterUnassigned).check();
    await expect(page.locator("article")).toHaveCount(0, { timeout: 20_000 });
    await page.getByLabel(ar.leads.filterUnassigned).uncheck();
    await expect.poll(async () => page.locator("article").count(), { timeout: 20_000 }).toBeGreaterThan(0);
  });

  test("a username portal login sees its own policy file", async ({ page, request, browser }, testInfo) => {
    test.skip(desktopOnly(testInfo), "1440×900 client-file dialog (ADR-019)");
    await phase2On(request);
    const auth = await apiLogin(request, MANAGER);
    const ownerAuth = await apiLogin(request, OWNER);
    const ownerClient = (await (await request.get("/api/v1/portal/overview", { headers: ownerAuth })).json()).client.id as string;

    // one issued policy for that company, arranged through the API (the issuing itself is the test above)
    const draft = await request.post("/api/v1/policies", {
      headers: auth,
      data: { client_id: ownerClient, start_date: "2026-11-01", end_date: "2027-10-31", premium_amount: 180000 },
    });
    expect(draft.status(), await draft.text()).toBe(201);
    const issued = await request.post(`/api/v1/policies/${(await draft.json()).id}/issue`, { headers: auth });
    expect(issued.status(), await issued.text()).toBe(200);
    const policyNo = (await issued.json()).policy_no as string;

    // the login is created from the client file, by a manager, and the temp password is shown once
    const username = unique("qa.portal");
    await login(page, MANAGER);
    await page.goto(`/clients/${ownerClient}`);
    await expect(page.getByRole("tablist", { name: ar.clients.file.title })).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: ar.clients.portal.create }).click();
    await page.getByLabel(ar.clients.portal.username).fill(username);
    await page.getByRole("button", { name: ar.common.confirm }).click();

    const password = page.locator("dd.font-mono");
    await expect(password).toBeVisible({ timeout: 20_000 });
    const temp = (await password.textContent())?.trim() ?? "";
    expect(temp.length).toBeGreaterThan(7);
    await page.getByRole("button", { name: ar.common.close, exact: true }).click();

    // a fresh context: the owner signs in with the username, and the API honours it
    const ownerContext = await browser.newContext();
    const ownerPage = await ownerContext.newPage();
    try {
      await login(ownerPage, username, temp);
      await expect(ownerPage).toHaveURL(/\/portal/, { timeout: 20_000 });
      await expect(ownerPage.getByText(policyNo)).toBeVisible({ timeout: 20_000 });

      const [file] = await Promise.all([ownerPage.waitForEvent("download"), ownerPage.getByLabel(ar.common.download).first().click()]);
      expect(file.suggestedFilename().toLowerCase()).toMatch(/\.pdf$/);

      // and none of the staff vocabulary reaches the portal
      const text = (await ownerPage.locator("body").textContent()) ?? "";
      expect(text).not.toContain(ar.leads.filterRep);
      expect(text).not.toContain("عمولة");
    } finally {
      await ownerContext.close();
    }
  });
});
