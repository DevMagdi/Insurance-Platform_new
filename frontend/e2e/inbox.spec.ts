import { expect, test } from "@playwright/test";

import { apiLogin, login, MANAGER, openFirstRequest, REPS } from "./fixtures";

test.describe("unified inbox (screen 2)", () => {
  test("a reply is written into the thread and stamps the first response", async ({ page, request }) => {
    await login(page, REPS.sara);
    const requestId = await openFirstRequest(page);
    expect(requestId).toBeTruthy();

    const body = `رد من اختبار الواجهة ${Date.now()}`;
    await page.getByLabel("اكتب ردك…", { exact: true }).fill(body);
    await page.getByRole("button", { name: "إرسال", exact: true }).click();
    await expect(page.getByText(body)).toBeVisible({ timeout: 15_000 });

    // the server is the source of truth: the reply is in the thread and first response is stamped
    const auth = await apiLogin(request, REPS.sara);
    const response = await request.get(`/api/v1/requests/${requestId}`, { headers: auth });
    expect(response.ok()).toBeTruthy();
    const detail = await response.json();
    expect(detail.messages.some((message: { body: string }) => message.body === body)).toBeTruthy();
    expect(detail.first_response_at, "first_response_at must be set after the first staff reply").not.toBeNull();
  });

  test("an internal note is saved against the request", async ({ page }) => {
    await login(page, REPS.sara);
    await openFirstRequest(page);
    const note = `ملاحظة ${Date.now()}`;
    await page.getByLabel("ملاحظة داخلية", { exact: true }).fill(note);
    await page.getByRole("button", { name: "حفظ", exact: true }).click();
    await expect(page.getByText(note)).toBeVisible({ timeout: 15_000 });
  });

  test("an inbound call from the simulator produces a playable recording", async ({ page, request }) => {
    // recordings are gated on calls.listen, which the sales rep role deliberately does not have
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

    // and the inbox thread renders the call row for that request
    if (payload.request_id) {
      await page.goto(`/inbox/${payload.request_id}`);
      await expect(page.getByText(/مكالمة واردة|Call log/).first()).toBeVisible({ timeout: 15_000 });
    }
  });
});
