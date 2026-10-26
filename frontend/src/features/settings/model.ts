/**
 * The settings hub's logic without JSX, so the rules that matter are testable without a browser —
 * the same reason `app/navModel.ts` exists (ADR-014/015/016).
 *
 * Three rules live here because each one is a promise the API also makes:
 *  1. a stored secret is *never* edited in place: the form holds a blank field meaning "leave it",
 *     an explicit removal meaning `null`, and a typed value meaning "replace" (ADR-016 §2);
 *  2. the badge in a provider card is derived from the row, never chosen by eye (ADR-016 §5);
 *  3. «تبديل إلى الحيّ» is explained by what is missing, not refused silently.
 */
import type { components } from "@/lib/api/schema";

export type ProviderState = components["schemas"]["ProviderStateOut"];
export type SecretField = components["schemas"]["SecretFieldOut"];

export type ProviderKey = "whatsapp" | "telephony" | "email";

export const PROVIDERS: readonly { key: ProviderKey; nameKey: string; noteKey: string }[] = [
  { key: "whatsapp", nameKey: "settings.provider.whatsapp", noteKey: "settings.provider.whatsappNote" },
  { key: "telephony", nameKey: "settings.provider.telephony", noteKey: "settings.provider.telephonyNote" },
  { key: "email", nameKey: "settings.provider.email", noteKey: "settings.provider.emailNote" },
] as const;

/** What the API prints instead of a stored secret. Anything equal to it means "untouched". */
export const MASK = "••••••••";

/** One edited secret field: blank = keep, `remove` = delete, text = replace. */
export interface SecretDraft {
  value: string;
  remove: boolean;
}

export function secretPatch(initial: readonly SecretField[], drafts: Record<string, SecretDraft>): Record<string, string | null> {
  const patch: Record<string, string | null> = {};
  for (const field of initial) {
    const draft = drafts[field.key];
    if (!draft) continue;
    if (draft.remove) {
      patch[field.key] = null;
      continue;
    }
    const typed = draft.value.trim();
    if (!typed || typed === MASK) continue; // the form echoes nothing, so nothing changes
    patch[field.key] = typed;
  }
  return patch;
}

/** True when the user actually changed a secret — so a config-only save sends no `secrets` key at all. */
export function hasSecretChanges(initial: readonly SecretField[], drafts: Record<string, SecretDraft>): boolean {
  return Object.keys(secretPatch(initial, drafts)).length > 0;
}

export type StatusKey = "live" | "sim" | "unset" | "error";

/**
 * The four badge tones of the screen, pinned to the token set: `t` live, `b` simulated, `r` failing,
 * and *no* accent color for "not configured" — neutral means the `--line-2`/`--muted` pair, which is
 * why this returns `null` instead of inventing a sixth tone (ADR-016 §5).
 */
export const STATUS_BADGE: Record<StatusKey, { tone: "t" | "b" | "r" | null; labelKey: string }> = {
  live: { tone: "t", labelKey: "settings.status.live" },
  sim: { tone: "b", labelKey: "settings.status.sim" },
  unset: { tone: null, labelKey: "settings.status.unset" },
  error: { tone: "r", labelKey: "settings.status.error" },
};

export function statusBadge(status: string | null | undefined): { tone: "t" | "b" | "r" | null; labelKey: string } {
  const key = status === "live" || status === "sim" || status === "error" ? status : "unset";
  return STATUS_BADGE[key];
}

/**
 * What the operator still has to fix before «التبديل إلى الحيّ» can succeed, in the order the server
 * checks it (ADR-016 §3): a green test, then the fields the provider cannot work without. The explicit
 * confirmation is *not* listed — the dialog always supplies it, so it is never something to fix.
 */
export function liveBlockers(state: ProviderState): ("test" | "fields")[] {
  const blockers: ("test" | "fields")[] = [];
  if (state.last_test_status !== "ok") blockers.push("test");
  if (missingLiveFields(state).length > 0) blockers.push("fields");
  return blockers;
}

/** The fields a provider needs before it may talk to customers, as the row reports them. */
export function missingLiveFields(state: ProviderState): string[] {
  const missing: string[] = [];
  if (state.provider === "whatsapp" && !String(state.config?.phone_number_id ?? "").trim()) missing.push("phone_number_id");
  if (state.provider === "email" && !String(state.config?.host ?? "").trim()) missing.push("host");
  const primary = { whatsapp: "access_token", telephony: "webhook_secret", email: "password" }[state.provider as ProviderKey];
  if (primary && !state.secrets?.some((item) => item.key === primary && item.set)) missing.push(primary);
  return missing;
}

/** `409 {details: {missing: [...]}}` → the labels to put next to the offending inputs. */
export function missingFromDetails(details: unknown): string[] {
  if (!details || typeof details !== "object") return [];
  const missing = (details as { missing?: unknown }).missing;
  return Array.isArray(missing) ? missing.filter((item): item is string => typeof item === "string") : [];
}

/** `429 {details: {retry_after_seconds}}` → a countdown the operator can act on. */
export function retryAfterSeconds(details: unknown): number | null {
  if (!details || typeof details !== "object") return null;
  const raw = (details as { retry_after_seconds?: unknown }).retry_after_seconds;
  return typeof raw === "number" && raw > 0 ? Math.ceil(raw) : null;
}

export interface SettingsTab {
  key: "integrations" | "policies" | "users";
  labelKey: string;
  /** The tab is mounted only when the caller holds all of these (`users` also needs `users.manage`). */
  permit: string[];
}

export const SETTINGS_TABS: readonly SettingsTab[] = [
  { key: "integrations", labelKey: "settings.tab.integrations", permit: ["settings.manage"] },
  { key: "policies", labelKey: "settings.tab.policies", permit: ["settings.manage"] },
  { key: "users", labelKey: "settings.tab.users", permit: ["settings.manage", "users.manage"] },
] as const;

export function visibleTabs(permissions: readonly string[]): SettingsTab[] {
  return SETTINGS_TABS.filter((tab) => tab.permit.every((perm) => permissions.includes(perm)));
}

export const PAYMENT_PLANS = ["monthly", "quarterly", "semiannual", "cash"] as const;

/**
 * Mirrors `INSTALLMENTS_BY_PLAN` in `app/services/policies.py`; `tests/settingsView.test.tsx` reads the
 * backend source and pins the copy, because a schedule the UI promises and the service does not build is
 * the same class of defect as a hardcoded badge count (ADR-015).
 */
export const INSTALLMENTS_BY_PLAN: Record<(typeof PAYMENT_PLANS)[number], number> = {
  monthly: 12,
  quarterly: 4,
  semiannual: 2,
  cash: 1,
};

/** The inbound-event rows the hub lists under the provider cards (`webhook_events`, ADR-016 §4). */
export type EventRow = components["schemas"]["WebhookEventOut"];
export type WebhookUrls = components["schemas"]["WebhookUrlsOut"];
