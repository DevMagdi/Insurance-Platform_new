import { expect, test } from "@playwright/test";

import { apiLogin, CS, login, MANAGER, openFirstRequest, REPS } from "./fixtures";

/**
 * Screen 2 — the unified inbox. The role here matters: the queue is a customer-service surface, its API
 * requires `requests.view`, and a sales rep is answered 403 (the rep's own dashboard is covered in
 * dashboard.spec.ts). Every assertion below is written against the person who can load the screen.
 */
test.describe("unified inbox (screen 2)", () => {
  test("a reply is written into the thread and stamps the first response", async ({ page, request }) => {
    await login(page, CS);
    const requestId = await openFirstRequest(page);
    expect(requestId).toBeTruthy();

    const body = `رد من اختبار الواجهة ${Date.now()}`;
    await page.getByLabel("اكتب ردك…", { exact: true }).fill(body);
    await page.getByRole("button", { name: "إرسال", exact: true }).click();
    await expect(page.getByText(body)).toBeVisible({ timeout: 15_000 });

    // the server is the source of truth: the reply is in the thread and first response is stamped
    const auth = await apiLogin(request, CS);
    const response = await request.get(`/api/v1/requests/${requestId}`, { headers: auth });
    expect(response.ok()).toBeTruthy();
    const detail = await response.json();
    expect(detail.messages.some((message: { body: string }) => message.body === body)).toBeTruthy();
    expect(detail.first_response_at, "first_response_at must be set after the first staff reply").not.toBeNull();
  });

  test("an internal note is saved against the request", async ({ page }) => {
    await login(page, CS);
    await openFirstRequest(page);
    const note = `ملاحظة ${Date.now()}`;
    await page.getByLabel("ملاحظة داخلية", { exact: true }).fill(note);
    await page.getByRole("button", { name: "حفظ", exact: true }).click();
    await expect(page.getByText(note)).toBeVisible({ timeout: 15_000 });
  });

  test("a sales rep is refused the queue, and the app says so instead of showing empty tiles", async ({ page, request }) => {
    const auth = await apiLogin(request, REPS.sara);
    const refused = await request.get("/api/v1/requests?limit=1", { headers: auth });
    expect(refused.status()).toBe(403);
    expect((await refused.json()).code).toBe("forbidden");

    await login(page, REPS.sara);
    await page.goto("/inbox");
    await expect(page.getByText(/لا تملك صلاحية|No access|forbidden/i).first()).toBeVisible({ timeout: 15_000 });
  });

  test("an inbound call from the simulator produces a playable recording", async ({ page, request }) => {
    // recordings are gated on calls.listen, which the customer-service role has and the rep does not
    const auth = await apiLogin(request, MANAGER);
    const call = await request.post("/api/v1/dev/sim/call", {
      data: { from_number: "01001234567", caller_name: "أحمد من شركة منطق", duration_s: 74, with_recording: true },
      headers: auth,
    });
    expect(call.ok()).toBeTruthy();
    const payload = await call.json();
    expect(payload.call_id).toBeTruthy();

    // staff with calls.listen get a short-TTL signed URL
    const url = await request.get(`/api/v1/calls/${payload.call_id}/recording-url`, { headers: auth });
    expect(url.ok()).toBeTruthy();
    const signed = (await url.json()).url as string;
    expect(signed).toContain("sig=");
    expect(signed).toContain("expires=");

    const played = await request.get(signed);
    expect(played.status()).toBe(200);
    expect((await played.body()).byteLength).toBeGreaterThan(0);

    if (payload.request_id) {
      // the page needs its own session: an unauthenticated goto lands on /login, not on the thread
      await login(page, MANAGER);
      await page.goto(`/inbox/${payload.request_id}`);
      const caller = page.getByText("أحمد من شركة منطق", { exact: true }).first();
      await expect(caller).toBeVisible({ timeout: 15_000 });
      // the row exposes a play button only because this role holds calls.listen
      await expect(page.getByRole("button", { name: "تشغيل", exact: true }).first()).toBeVisible();
      expect(payload.matched_kind, "the caller matched a known client, so the call is linked").toBeTruthy();
    }
  });
});
