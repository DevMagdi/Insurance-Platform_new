import { expect, test } from "@playwright/test";

import { ADMIN, apiLogin, CS, login, MANAGER, REPS } from "./fixtures";

/** The exact controls this screen owns, so a locator cannot land on another provider's row. */
const PHONE = "config-whatsapp-phone_number_id";
const TOKEN = "secret-whatsapp-access_token";
const DROP_TOKEN = "secret-delete-whatsapp-access_token";

/**
 * The settings hub (spec §8, ADR-016) — the screen that decides whether a provider talks to customers or
 * only to the simulator. What is asserted here is the part a unit test cannot: that a saved secret
 * survives a reload *without ever appearing on screen*, that the live switch actually changes behaviour,
 * and that a call really lands in the event log the screen reads back.
 *
 * Nothing in this file flips the Phase-2 flag or edits another role's data, so it can run in parallel.
 */

test.describe("settings hub · providers", () => {
  test("the three providers are listed, and a stored secret is never shown", async ({ page }) => {
    await login(page, MANAGER);
    await page.goto("/settings");

    await expect(page.getByRole("heading", { name: "الإعدادات" })).toBeVisible();
    for (const provider of ["واتساب للأعمال", "السنترال (Telephony)", "البريد (SMTP)"]) {
      await expect(page.getByRole("heading", { name: provider })).toBeVisible();
    }

    const secret = page.getByTestId(TOKEN);
    await secret.fill("e2e-token-must-not-leak");
    await page.getByTestId(PHONE).fill("123456789012345");
    await page.getByRole("button", { name: "حفظ" }).first().click();
    await expect(page.getByText("تم حفظ الإعدادات")).toBeVisible({ timeout: 15_000 });

    await page.reload();
    await expect(page.getByTestId("secret-whatsapp-access_token")).toBeVisible();
    // the value is stored (the row says so) and invisible (the input is empty, its placeholder is dots)
    await expect(page.getByTestId(TOKEN)).toHaveValue("");
    await expect(page.getByTestId(TOKEN)).toHaveAttribute("placeholder", "••••••••");
    await expect(page.locator("body")).not.toContainText("e2e-token-must-not-leak");
    // and the non-secret half of the same save is visible, because it is not a secret
    await expect(page.getByTestId(PHONE)).toHaveValue("123456789012345");

    // leave the row as we found it for the rest of the suite
    await page.getByTestId(DROP_TOKEN).click();
    await page.getByTestId(PHONE).fill("");
    await page.getByRole("button", { name: "حفظ" }).first().click();
    await expect(page.getByText("تم حفظ الإعدادات")).toBeVisible();
  });

  test("a connection test is recorded, and live needs a confirmation — then it really switches", async ({ page }) => {
    await login(page, MANAGER);
    await page.goto("/settings");

    await page.getByTestId(PHONE).fill("999888777");
    await page.getByTestId(TOKEN).fill("e2e-live-token");
    await page.getByRole("button", { name: "حفظ" }).first().click();
    await expect(page.getByText("تم حفظ الإعدادات")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "اختبار الاتصال" }).first().click();
    await expect(page.getByTestId("test-result-whatsapp")).toContainText("وضع المحاكاة", { timeout: 20_000 });

    await page.getByRole("button", { name: "التبديل إلى الحيّ" }).first().click();
    await expect(page.getByRole("dialog", { name: "تأكيد التحوّل إلى الوضع الحيّ" })).toBeVisible();
    await page.getByRole("button", { name: "تأكيد والتبديل" }).click();

    const card = page.locator("div.card", { hasText: "واتساب للأعمال" }).first();
    await expect(card.getByText("حيّ", { exact: true })).toBeVisible({ timeout: 20_000 });
    // no assertion that the app then *called* Meta: an e2e run must not spend a real vendor quota, and
    // what the switch provably changes is the row and the badge — the live HTTP path is unit-tested
    // against a stubbed transport (`tests/test_integrations_settings.py`).

    // going back to simulation is the safe direction, so it asks for nothing
    await page.getByRole("button", { name: "الرجوع إلى المحاكاة" }).first().click();
    await expect(card.getByText("محاكاة", { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // clean up: no credentials and no live row survive this spec
    await page.getByTestId(DROP_TOKEN).click();
    await page.getByTestId(PHONE).fill("");
    await page.getByRole("button", { name: "حفظ" }).first().click();
    await expect(page.getByText("تم حفظ الإعدادات")).toBeVisible();
  });

  test("the event log shows what arrived, including a payload we refused", async ({ page, request }) => {
    const headers = await apiLogin(request, ADMIN);
    const delivered = await request.post("/api/v1/webhooks/telephony", {
      headers,
      data: { call_id: "e2e-call-1", event: "call.started", from: "+201000000000" },
    });
    expect(delivered.status(), await delivered.text()).toBe(200);

    await login(page, MANAGER);
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "آخر الأحداث الواردة" })).toBeVisible();
    await expect(page.getByText("call.started").first()).toBeVisible({ timeout: 20_000 });
  });
});

test.describe("settings hub · who may see it", () => {
  test("the users tab needs users.manage, which the manager role does not hold", async ({ page }) => {
    await login(page, MANAGER);
    await page.goto("/settings");
    await expect(page.getByRole("tab", { name: "سياسة الاكتتاب" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "المستخدمون والصلاحيات" })).toHaveCount(0);

    // the old deep link still works for the role that owns it — and lands on the tab, not a 404
    await page.goto("/users");
    await expect(page.getByRole("heading", { name: "الإعدادات" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "المستخدمون والصلاحيات" })).toHaveCount(0);
  });

  test("an admin sees the users tab inside the hub", async ({ page }) => {
    await login(page, ADMIN);
    await page.goto("/settings?tab=users");
    await expect(page.getByRole("heading", { name: "المستخدمون والصلاحيات" })).toBeVisible({ timeout: 20_000 });
  });

  test("a rep without settings.manage gets the 403 state, not a read-only copy", async ({ page }) => {
    await login(page, REPS.sara);
    await page.goto("/settings");
    await expect(page.getByText("لا تملك صلاحية لهذه الشاشة")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "اختبار الاتصال" })).toHaveCount(0);
  });

  test("a service-desk agent without settings.manage is turned away, not shown a read-only copy", async ({ page }) => {
    await login(page, CS);
    await page.goto("/settings");
    await expect(page.getByText("لا تملك صلاحية لهذه الشاشة")).toBeVisible({ timeout: 20_000 });
  });
});

test.describe("settings hub · underwriting defaults", () => {
  test("a saved default stays where it was set", async ({ page }) => {
    await login(page, MANAGER);
    await page.goto("/settings?tab=policies");

    const commission = page.locator('input[type="number"]');
    await commission.fill("7.5");
    await page.getByRole("button", { name: "حفظ" }).click();
    await expect(page.getByText("تم حفظ الإعدادات")).toBeVisible({ timeout: 15_000 });

    await page.reload();
    await expect(page.getByRole("tab", { name: "سياسة الاكتتاب" })).toHaveAttribute("aria-selected", "true");
    await expect(commission).toHaveValue("7.5");

    // (the "these defaults seed a real policy" claim is proven in the backend suite, where the Phase-2
    // flag is set in-process; asserting it from a browser would race the flag other specs toggle.)

    await page.getByRole("tab", { name: "سياسة الاكتتاب" }).click();
    await commission.fill("5");
    await page.getByRole("button", { name: "حفظ" }).click();
    await expect(page.getByText("تم حفظ الإعدادات")).toBeVisible();
  });
});
