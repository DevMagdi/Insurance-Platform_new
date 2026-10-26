import { expect, test } from "@playwright/test";

import { login, OWNER, PASSWORD, REPS } from "./fixtures";

test.describe("authentication", () => {
  test("a rep lands on the dashboard with their own KPI row", async ({ page }) => {
    await login(page, REPS.sara);
    await expect(page.getByRole("heading", { name: "لوحة التحكم" })).toBeVisible();
    await expect(page.getByText("طلبات اليوم")).toBeVisible();
    await expect(page.getByText("نسبة الالتزام بالـ SLA")).toBeVisible();
  });

  test("a wrong password is refused with the server's own message", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/البريد الإلكتروني/).fill(REPS.sara);
    await page.getByLabel(/كلمة المرور/).fill("not-the-password");
    await page.getByRole("button", { name: "دخول", exact: true }).click();
    await expect(page.getByText(/بيانات الدخول غير صحيحة|خطوة|غير صحيحة/).first()).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("the client owner is routed to the portal, never to the staff shell", async ({ page }) => {
    await login(page, OWNER);
    await expect(page.getByText("بوابة العميل")).toBeVisible();
    await expect(page.getByRole("navigation")).toHaveCount(0);
  });

  test("an authenticated session survives a reload (refresh cookie rotation)", async ({ page }) => {
    await login(page, REPS.nour);
    await page.reload();
    await expect(page.getByRole("heading", { name: "لوحة التحكم" })).toBeVisible({ timeout: 15_000 });
    await page.context().clearCookies();
    // the access token is short-lived; with the refresh cookie gone the next call must bounce
    await expect(async () => {
      await page.goto("/inbox");
      await expect(page.getByRole("heading", { name: "صندوق الطلبات" })).toHaveCount(0);
    }).toPass({ timeout: 15_000 });
    expect(PASSWORD.length).toBeGreaterThan(8);
  });
});
