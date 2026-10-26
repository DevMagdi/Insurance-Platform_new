import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** The API origin the panel and the Vite proxy both point at (see frontend/.env.example). */
export const API_ORIGIN = process.env.VITE_API_ORIGIN ?? "http://127.0.0.1:8000";

/** Demo credentials come from `python -m app.seed` — fictitious people only (spec rule 4). */
export const PASSWORD = "Br0kerHub!2026";
export const REPS = {
  sara: "sara.elsayed@brokerhub.test",
  nour: "nour.fahmy@brokerhub.test",
} as const;
export const MANAGER = "manager@brokerhub.test";
export const CS = "cs@brokerhub.test";
export const OWNER = "owner.mantiq@company.test";

const EMAIL_FIELD = /البريد الإلكتروني/;
const PASSWORD_FIELD = /كلمة المرور/;
const SUBMIT = { name: "تسجيل الدخول", exact: true } as const;

/** Log in through the real form, so the refresh cookie + profile fetch are exercised too. */
export async function login(page: Page, email: string, password = PASSWORD) {
  await page.goto("/login");
  await page.getByLabel(EMAIL_FIELD).fill(email);
  await page.getByLabel(PASSWORD_FIELD).fill(password);
  await page.getByRole("button", SUBMIT).click();
  await page.waitForURL(/\/(dashboard|portal|inbox)/, { timeout: 20_000 });
}

/** API session for arranging data — goes through the same proxied /api the browser uses. */
export async function apiLogin(request: APIRequestContext, email: string, password = PASSWORD) {
  const response = await request.post("/api/v1/auth/login", { data: { email, password, remember_me: true } });
  expect(response.ok(), `login failed for ${email}`).toBeTruthy();
  const token = (await response.json()).access_token as string;
  return { authorization: `Bearer ${token}` };
}

/** Open a request from the inbox queue (the first row that matches, or the first row at all). */
export async function openFirstRequest(page: Page) {
  await page.goto("/inbox");
  const row = page.locator("[data-request-row]").first();
  await expect(row).toBeVisible({ timeout: 20_000 });
  const requestId = await row.getAttribute("data-request-row");
  await row.click();
  return requestId;
}
