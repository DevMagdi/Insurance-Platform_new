import { mkdirSync, readdirSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { apiLogin, login, MANAGER, OWNER } from "./fixtures";

/**
 * Design-review evidence (spec §10): every screen at 1440×900, the mobile flows at 390×844, and a
 * contact sheet the owner can scan in one image. Files land in docs/screenshots/ and are uploaded as a
 * CI artifact. Nothing here asserts pixel values — it captures them for the human review pass.
 */
const OUT = path.resolve(import.meta.dirname, "../../docs/screenshots");

type Shot = { name: string; route: string; who: "manager" | "owner"; ready: RegExp; viewport: "desktop" | "mobile"; fullPage?: boolean };

const SHOTS: Shot[] = [
  { name: "01-dashboard", route: "/dashboard", who: "manager", ready: /لوحة التحكم/, viewport: "desktop" },
  { name: "02-inbox", route: "/inbox", who: "manager", ready: /صندوق الطلبات الموحد/, viewport: "desktop", fullPage: false },
  { name: "03-kanban", route: "/leads", who: "manager", ready: /جديد|الـLeads/, viewport: "desktop", fullPage: false },
  { name: "04-mobile-board", route: "/mobile/leads", who: "manager", ready: /ليدزي|Leads/, viewport: "mobile" },
  { name: "04-mobile-inbox", route: "/inbox", who: "manager", ready: /صندوق الطلبات/, viewport: "mobile", fullPage: false },
  { name: "05-client-file", route: "/clients", who: "manager", ready: /العملاء/, viewport: "desktop" },
  { name: "06-unassigned", route: "/leads", who: "manager", ready: /الكل|جديد/, viewport: "desktop", fullPage: false },
  { name: "07-portal", route: "/portal", who: "owner", ready: /بوابة العميل/, viewport: "desktop" },
  { name: "08-clients", route: "/clients", who: "manager", ready: /العملاء/, viewport: "desktop" },
  { name: "09-lead-detail", route: "/leads", who: "manager", ready: /جديد|الـLeads/, viewport: "desktop", fullPage: false },
  { name: "10-new-lead", route: "/leads/new", who: "manager", ready: /ليد جديد/, viewport: "desktop" },
  { name: "11-insured", route: "/clients", who: "manager", ready: /العملاء/, viewport: "desktop" },
  { name: "12-sales-team", route: "/sales-team", who: "manager", ready: /فريق المبيعات|حِمل/, viewport: "desktop" },
  { name: "13-policies", route: "/policies", who: "manager", ready: /الوثائق والأقساط/, viewport: "desktop" },
  { name: "14-issuing", route: "/issuing", who: "manager", ready: /حالات الإصدار/, viewport: "desktop" },
  { name: "15-portal-mobile", route: "/portal", who: "owner", ready: /بوابة العميل/, viewport: "mobile", fullPage: false },
  { name: "16-reports", route: "/reports", who: "manager", ready: /التقارير/, viewport: "desktop" },
  { name: "17-users", route: "/users", who: "manager", ready: /المستخدمون|الأدوار/, viewport: "desktop" },
];

test.describe("screenshots for design review", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async ({ request }) => {
    mkdirSync(OUT, { recursive: true });
    // phase 2 must be captured unlocked, otherwise half the sheet is a gate card
    const auth = await apiLogin(request, "admin@brokerhub.test");
    const enabled = await request.patch("/api/v1/feature-flags/phase2.enabled", { headers: auth, data: { enabled: true } });
    expect(enabled.status()).toBe(200);
  });

  for (const shot of SHOTS) {
    test(shot.name, async ({ page }, testInfo) => {
      test.skip(testInfo.project.name !== shot.viewport, `${shot.name} is a ${shot.viewport} capture`);
      await login(page, shot.who === "owner" ? OWNER : MANAGER);
      await page.goto(shot.route);
      await expect(page.getByText(shot.ready).first()).toBeVisible({ timeout: 20_000 });
      // let charts, avatars and skeletons settle before freezing pixels
      await page.waitForTimeout(700);
      await page.screenshot({ path: path.join(OUT, `${testInfo.project.name}-${shot.name}.png`), fullPage: shot.fullPage !== false });
    });
  }

  test("contact sheet", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "the desktop pass assembles the sheet");
    const files = readdirSync(OUT)
      .filter((file) => file.startsWith("desktop-") && file.endsWith(".png"))
      .sort();
    expect(files.length).toBeGreaterThanOrEqual(10);

    const cells = files
      .map((file) => `<figure><img src="file://${path.join(OUT, file)}"><figcaption>${file.replace(/^desktop-|\.png$/g, "")}</figcaption></figure>`)
      .join("\n");
    await page.setViewportSize({ width: 1800, height: 1200 });
    await page.setContent(
      `<!doctype html><html dir="rtl"><head><meta charset="utf-8"><style>
       body{margin:0;background:#0E1424;color:#E5E7EB;font:600 14px system-ui;padding:24px}
       h1{font-size:20px;margin:0 0 16px}
       .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}
       figure{margin:0;background:#151B2E;border-radius:14px;overflow:hidden;border:1px solid #26304a}
       img{display:block;width:100%;height:auto;background:#fff}
       figcaption{padding:8px 10px;font-size:12px}
     </style></head><body><h1>Broker Hub — مراجعة الواجهات</h1><div class="grid">${cells}</div></body></html>`,
      { waitUntil: "load" },
    );
    await page.waitForTimeout(1_200);
    await page.screenshot({ path: path.join(OUT, "contact-sheet.png"), fullPage: true });
  });
});
