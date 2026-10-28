import { expect, test } from "@playwright/test";

import { login, MANAGER, REPS } from "./fixtures";

/** ERP hub (ADR-031): manager reaches /erp, switches period, opens the ledger; a rep never sees ERP. */
test.describe("ERP accounting hub", () => {
  test("manager opens /erp, switches period and opens the ledger from a card", async ({ page }) => {
    await login(page, MANAGER);
    await page.getByRole("link", { name: /ERP المحاسبي/ }).first().click();
    await expect(page).toHaveURL(/\/erp$/);
    await expect(page.getByRole("heading", { name: "ERP المحاسبي" })).toBeVisible();
    await page.getByRole("button", { name: "سنوي" }).click();
    await expect(page.getByText("صُرف / دخل على إيه", { exact: false })).toBeVisible();
    await page.getByRole("link", { name: /دفتر الحركات/ }).first().click();
    await expect(page).toHaveURL(/\/finance\/ledger$/);
  });

  test("a rep does not see the ERP item and /erp is refused", async ({ page }) => {
    await login(page, REPS.sara);
    await expect(page.getByRole("link", { name: /ERP المحاسبي/ })).toHaveCount(0);
    await page.goto("/erp");
    await expect(page.getByText("403")).toBeVisible();
  });
});
