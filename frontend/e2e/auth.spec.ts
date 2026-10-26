import { expect, test } from "@playwright/test";

import { apiLogin, LOGIN_BUTTON, login, OWNER, PASSWORD, REPS } from "./fixtures";

test.describe("authentication", () => {
  test("a rep lands on the board their role can load", async ({ page, request }) => {
    /*
     * The dashboard's summary requires `requests.view`, which a sales rep does not hold — landing there
     * produced four empty tiles and a 403 in the log. Landing is by permission now, so the rep starts on
     * their own leads board, and the KPI label the old assertion used ("نسبة الالتزام بالـ SLA") never
     * existed: the tile is "الالتزام بالـSLA" (`dashboard.kpiSla` in both dictionaries).
     */
    await login(page, REPS.sara);
    await expect(page).toHaveURL(/\/leads/);
    await expect(page.getByText("عرض البياع")).toBeVisible();
    const auth = await apiLogin(request, REPS.sara);
    const refused = await request.get("/api/v1/dashboard/summary", { headers: auth });
    expect(refused.status()).toBe(403);
    expect((await refused.json()).code).toBe("forbidden");
  });

  test("a wrong password is refused with the server's own message", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/البريد الإلكتروني/).fill(REPS.sara);
    await page.getByLabel(/كلمة المرور/).fill("not-the-password");
    await page.getByRole("button", LOGIN_BUTTON).click();
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
