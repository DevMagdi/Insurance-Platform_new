import { expect, test } from "@playwright/test";

import { ADMIN, apiLogin, CS, login, MANAGER, REPS } from "./fixtures";

/**
 * The settings hub (spec §8, ADR-016) — the screen that decides whether a provider talks to customers or
 * only to the simulator. What is asserted here is what a unit test cannot: that a saved secret survives a
 * reload *without ever appearing on screen*, that the live switch refuses an untested provider and says why,
 * and that an inbound event really lands in the log the screen reads back.
 *
 * Viewports: the interactive pass is desktop-only on purpose. The hub's cards sit under a fixed mobile bar
 * at 390px, and an assertion that fights a sticky element proves nothing about the feature; the mobile
 * rendering is covered by `15b-settings-hub.png` in the screenshots job. Same split as `simulator.spec.ts`.
 *
 * No live click on «اختبار الاتصال» while a row is live: CI must not spend a real Meta quota. What the flip
 * provably changes is the row and the badge; the live HTTP path is unit-tested against a stubbed transport
 * (`backend/tests/test_integrations_settings.py`).
 */

/** The exact controls this screen owns, so a locator cannot land on another provider's row. */
const PHONE = "config-whatsapp-phone_number_id";
const TOKEN = "secret-whatsapp-access_token";
const DROP_TOKEN = "secret-delete-whatsapp-access_token";

test.describe("settings hub · providers", () => {
  test("the three providers are listed, and a stored secret is never shown", async ({ page }) => {
    await login(page, MANAGER);
    await page.goto("/settings");

    await expect(page.getByRole("heading", { name: "الإعدادات" })).toBeVisible();
    for (const provider of ["واتساب للأعمال", "السنترال (Telephony)", "البريد (SMTP)"]) {
      await expect(page.getByRole("heading", { name: provider })).toBeVisible();
    }
    // the claim that matters on a phone too: every secret field exists, and none of them carries a value
    const values = await page
      .locator('input[type="password"]')
      .evaluateAll((nodes) => nodes.map((node) => (node as HTMLInputElement).value));
    expect(values.length).toBeGreaterThanOrEqual(6);
    expect(values.filter((value) => value !== "")).toEqual([]);
  });

  test("a saved secret survives a reload invisible, while the plain fields stay visible", async ({ page }) => {
    test.skip(test.info().project.name !== "desktop", "desktop-only — see the header");
    await login(page, MANAGER);
    await page.goto("/settings");

    await page.getByTestId(TOKEN).fill("e2e-token-must-not-leak");
    await page.getByTestId(PHONE).fill("123456789012345");
    await page.getByRole("button", { name: "حفظ" }).first().click();

    await page.reload();
    const secret = page.getByTestId(TOKEN);
    await expect(secret).toBeVisible();
    // stored (the row says so) and invisible (the input is empty; its placeholder is the mask)
    await expect(secret).toHaveValue("");
    await expect(secret).toHaveAttribute("placeholder", "••••••••");
    await expect(page.locator("body")).not.toContainText("e2e-token-must-not-leak");
    // and the non-secret half of the same save is visible, because it is not a secret
    await expect(page.getByTestId(PHONE)).toHaveValue("123456789012345");

    // leave the row as we found it for the rest of the suite
    await page.getByTestId(DROP_TOKEN).click();
    await page.getByTestId(PHONE).fill("");
    await page.getByRole("button", { name: "حفظ" }).first().click();
    await expect(page.getByText("تم حفظ الإعدادات")).toBeVisible({ timeout: 15_000 });
  });

  test("the live switch refuses an untested provider — before the click and after it", async ({ page }) => {
    test.skip(test.info().project.name !== "desktop", "desktop-only — see the header");
    // telephony is the row no other spec touches, so "never tested" is a fact here, not a race
    await login(page, MANAGER);
    await page.goto("/settings");

    const telephony = page.locator('section.card', { hasText: "السنترال (Telephony)" }).first();
    await expect(telephony.getByText("غير مُعدّ", { exact: true })).toBeVisible();

    await telephony.getByRole("button", { name: "التبديل إلى الحيّ" }).click();
    const dialog = page.getByRole("dialog", { name: "تأكيد التحوّل إلى الوضع الحيّ" });
    await expect(dialog).toBeVisible();
    // the screen warns before the request: a green test is a precondition, not a suggestion
    await expect(dialog.getByText("لم ينجح أي اختبار بعد")).toBeVisible();
    await dialog.getByRole("button", { name: "تأكيد والتبديل" }).click();
    await expect(page.getByText("لم ينجح أي اختبار اتصال لهذا المزوّد بعد")).toBeVisible({ timeout: 15_000 });
    await expect(telephony.getByText("غير مُعدّ", { exact: true })).toBeVisible(); // still refused, still sim
  });

  test("test → live really flips the badge, and going back asks for nothing", async ({ page }) => {
    test.skip(test.info().project.name !== "desktop", "desktop-only — see the header");
    await login(page, MANAGER);
    await page.goto("/settings");

    const whatsapp = page.locator('section.card', { hasText: "واتساب للأعمال" }).first();
    await page.getByTestId(PHONE).fill("999888777");
    await page.getByTestId(TOKEN).fill("e2e-live-token");
    await page.getByRole("button", { name: "حفظ" }).first().click();
    await expect(page.getByText("تم حفظ الإعدادات")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "اختبار الاتصال" }).first().click();
    await expect(page.getByTestId("test-result-whatsapp")).toContainText("وضع المحاكاة", { timeout: 20_000 });

    await whatsapp.getByRole("button", { name: "التبديل إلى الحيّ" }).click();
    await page.getByRole("dialog", { name: "تأكيد التحوّل إلى الوضع الحيّ" }).getByRole("button", { name: "تأكيد والتبديل" }).click();
    await expect(whatsapp.getByText("حيّ", { exact: true })).toBeVisible({ timeout: 20_000 });

    await whatsapp.getByRole("button", { name: "الرجوع إلى المحاكاة" }).click();
    await expect(whatsapp.getByText("محاكاة", { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("dialog")).toHaveCount(0); // the safe direction needs no confirmation

    await page.getByTestId(DROP_TOKEN).click();
    await page.getByTestId(PHONE).fill("");
    await page.getByRole("button", { name: "حفظ" }).first().click();
    await expect(page.getByText("تم حفظ الإعدادات")).toBeVisible({ timeout: 15_000 });
  });

  test("an inbound event is readable from the screen, without opening a server log", async ({ page, request }) => {
    test.skip(test.info().project.name !== "desktop", "desktop-only — see the header");
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

    // the old deep link still works for the role that owns it — and the role that does not gets the gate, not a read-only copy
    await page.goto("/users");
    await expect(page.getByRole("heading", { name: "الإعدادات" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "المستخدمون والصلاحيات" })).toHaveCount(0);
  });

  test("an admin sees the users tab inside the hub", async ({ page }) => {
    await login(page, ADMIN);
    await page.goto("/settings?tab=users");
    await expect(page.getByRole("heading", { name: "المستخدمون والصلاحيات" })).toBeVisible({ timeout: 20_000 });
  });

  test("a rep and a service-desk agent are turned away, not shown a read-only copy", async ({ page }) => {
    await login(page, REPS.sara);
    await page.goto("/settings");
    await expect(page.getByText("لا تملك صلاحية لهذه الشاشة")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "اختبار الاتصال" })).toHaveCount(0);

    await login(page, CS);
    await page.goto("/settings");
    await expect(page.getByText("لا تملك صلاحية لهذه الشاشة")).toBeVisible({ timeout: 20_000 });
  });
});

test.describe("settings hub · underwriting defaults", () => {
  test("a saved default is what the screen reads back after a reload", async ({ page }) => {
    test.skip(test.info().project.name !== "desktop", "desktop-only — see the header");
    await login(page, MANAGER);
    await page.goto("/settings?tab=policies");
    await expect(page.getByRole("heading", { name: "سياسة الاكتتاب" })).toBeVisible();

    const commission = page.locator('section.card input[type="number"]');
    await commission.fill("7.5");
    await page.getByRole("button", { name: "حفظ" }).click();
    await expect(page.getByText("تم حفظ سياسة الاكتتاب")).toBeVisible({ timeout: 15_000 });

    await page.reload();
    await expect(commission).toHaveValue("7.5"); // stored, not merely typed: this is a fresh document

    await commission.fill("5");
    await page.getByRole("button", { name: "حفظ" }).click();
    await expect(page.getByText("تم حفظ سياسة الاكتتاب")).toBeVisible({ timeout: 15_000 });
    // ("these defaults seed a real policy" is proven in the backend suite, where `phase2.enabled` is set
    // in-process; asserting it from a browser would race the flag another spec toggles.)
  });
});
