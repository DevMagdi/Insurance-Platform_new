/**
 * «التحويل إلى الوضع الحيّ» — the screen must not press a button the server will refuse (ADR-027).
 *
 * Three promises are checked here and each one was broken before R6:
 *  1. the button is disabled while a blocker exists, and the card names the blocker (test first, then fields);
 *  2. when the server does answer 409 — a stale screen, a second tab, an env change — the message carries the
 *     Arabic field labels and the card refreshes itself instead of staying on a screen that keeps failing;
 *  3. a partially-loaded provider row renders. `Cannot read properties of undefined (reading 'toLowerCase')`
 *     came from exactly this: code that trusted every field of an API response to be present.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProviderCard } from "@/features/settings/ProviderCard";
import { liveBlockersOf, liveSwitchError, missingLiveFields, statusBadge, type ProviderState } from "@/features/settings/model";
import { ar } from "@/lib/i18n/ar";
import { asText, includesText, lower, upper } from "@/lib/text";

const MASK = "••••••••";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({ api }));
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/components/Toast", () => ({ useToast: () => toast, ToastProvider: ({ children }: { children: React.ReactNode }) => children }));

function state(overrides: Partial<ProviderState> = {}): ProviderState {
  return {
    provider: "whatsapp",
    config: { phone_number_id: "12345", business_account_id: "", receive_media: true },
    secrets: [
      { key: "access_token", set: true, display: MASK },
      { key: "app_secret", set: true, display: MASK },
      { key: "verify_token", set: false, display: "not_set" },
    ],
    is_live: false,
    status: "sim",
    last_tested_at: "2026-10-27T09:00:00Z",
    last_test_status: "ok",
    last_test_detail: "green",
    updated_at: null,
    ...overrides,
  } as ProviderState;
}

function mount(provider: ProviderState) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: 0, gcTime: 0 }, mutations: { retry: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProviderCard state={provider} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function preflight(overrides: Record<string, unknown> = {}) {
  return {
    provider: "whatsapp",
    ready: true,
    blockers: [],
    missing: [],
    labels: [],
    is_live: false,
    mode: "sim",
    status: "sim",
    test_status: "ok",
    tested_at: "2026-10-27T09:00:00Z",
    next: "جاهز للتحويل",
    ...overrides,
  };
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.put.mockReset();
  toast.mockReset();
  api.get.mockResolvedValue(preflight());
});

describe("the live switch is gated on the server's own preflight", () => {
  it("disables the button and lists the missing fields the server names", async () => {
    api.get.mockResolvedValue(
      preflight({
        ready: false,
        missing: ["phone_number_id", "access_token"],
        labels: ["معرّف رقم واتساب (Phone Number ID)", "توكين الوصول (Access Token)"],
        blockers: [
          {
            code: "fields",
            message: "إعدادات ناقصة للوضع الحيّ: معرّف رقم واتساب (Phone Number ID)، توكين الوصول (Access Token)",
            fields: ["phone_number_id", "access_token"],
          },
        ],
      }),
    );
    mount(state({ config: { phone_number_id: "", business_account_id: "", receive_media: true } }));

    // the first paint uses the row we already have; the server's preflight then replaces it, and *its* list
    // is the authoritative one — both fields, and both names as they appear on the form
    await waitFor(() =>
      expect(screen.getByTestId("live-blockers-whatsapp").textContent).toContain(ar.settings.secret.access_token),
    );
    const reasons = screen.getByTestId("live-blockers-whatsapp");
    expect(reasons).toHaveTextContent(ar.settings.liveBlockedTitle);
    expect(reasons.textContent).toContain(ar.settings.field.phone_number_id);
    expect(screen.getByTestId("live-switch-whatsapp")).toBeDisabled();
  });

  it("asks for a green test before it asks for anything else", async () => {
    api.get.mockResolvedValue(
      preflight({
        ready: false,
        test_status: null,
        blockers: [{ code: "test", message: "لم ينجح أي اختبار اتصال لهذا المزوّد بعد", fields: [] }],
      }),
    );
    mount(state({ last_test_status: null }));
    await waitFor(() => expect(screen.getByTestId("live-blockers-whatsapp")).toHaveTextContent(ar.settings.liveBlockedTest));
    expect(screen.getByTestId("live-switch-whatsapp")).toBeDisabled();
  });

  it("sends the switch when the preflight is ready, and only then", async () => {
    api.post.mockResolvedValue(state({ is_live: true, status: "live" }));
    mount(state());

    await waitFor(() => expect(screen.getByTestId("live-switch-whatsapp")).toBeEnabled());
    fireEvent.click(screen.getByTestId("live-switch-whatsapp"));
    fireEvent.click(screen.getByRole("button", { name: ar.settings.confirmLive }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [path, body] = api.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/settings/integrations/whatsapp/live");
    expect(body).toMatchObject({ is_live: true, confirm: true });
  });

  it("turns a 409 into the exact Arabic fields, and re-reads the row", async () => {
    api.post.mockRejectedValue({
      message: "إعدادات ناقصة للوضع الحيّ",
      details: {
        provider: "whatsapp",
        blockers: [{ code: "fields", message: "إعدادات ناقصة للوضع الحيّ: معرّف رقم واتساب", fields: ["phone_number_id"] }],
        missing: ["phone_number_id"],
        labels: ["معرّف رقم واتساب (Phone Number ID)"],
        hint: "شغّل اختبار الاتصال، واملأ الحقول الناقصة",
      },
    });

    mount(state());
    await waitFor(() => expect(screen.getByTestId("live-switch-whatsapp")).toBeEnabled());
    fireEvent.click(screen.getByTestId("live-switch-whatsapp"));
    fireEvent.click(screen.getByRole("button", { name: ar.settings.confirmLive }));

    await waitFor(() => expect(toast).toHaveBeenCalled());
    const [message, tone] = toast.mock.calls[0] as [string, string];
    expect(tone).toBe("error");
    expect(message).toContain("معرّف رقم واتساب (Phone Number ID)");
    // and the dialog is closed — the card is usable again, not stuck mid-flight
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByTestId("live-switch-whatsapp")).toBeInTheDocument();
  });
});

describe("partial payloads never crash the card", () => {
  it("renders a provider row with no provider, no config and no secrets", () => {
    const broken = { status: undefined, config: undefined, secrets: undefined } as unknown as ProviderState;
    expect(() => mount(broken)).not.toThrow();
    // the preflight is not even requested without a provider key
    expect(api.get).not.toHaveBeenCalled();
  });

  it("guards every string helper the settings logic uses", () => {
    expect(statusBadge(undefined).labelKey).toBe("settings.status.unset");
    expect(statusBadge(null).labelKey).toBe("settings.status.unset");
    expect(missingLiveFields(undefined)).toEqual([]);
    expect(liveBlockersOf({ provider: "telephony" } as ProviderState)).toEqual([
      { code: "test", message: "", fields: [] },
      { code: "fields", message: "", fields: ["provider_url", "webhook_secret"] },
    ]);
    expect(liveSwitchError(undefined)).toEqual({ message: "", fields: [] });
    expect(liveSwitchError({ message: "boom" })).toEqual({ message: "boom", fields: [] });
  });

  it("never calls a string method on a missing value", () => {
    expect(asText(undefined)).toBe("");
    expect(asText(null)).toBe("");
    expect(lower(undefined)).toBe("");
    expect(upper(null)).toBe("");
    expect(includesText(undefined, "x")).toBe(false);
    expect(includesText("شركة ألف", "")).toBe(true);
    expect(includesText("ACME Corp", "acme")).toBe(true);
  });
});
