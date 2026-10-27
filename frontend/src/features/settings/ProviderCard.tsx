/**
 * One provider card: the values, the write-only secrets, the live switch, and the two things an operator
 * actually comes here for — «اختبار الاتصال» and the callback URL to paste into the vendor's console.
 *
 * The form is built from the fields the API returns, not from a list copied into the frontend: a setting
 * the backend stops offering would otherwise keep rendering here as a dead input forever.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, PlugZap, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/Modal";
import { Badge, Button, Card } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api/client";
import { relativeTime } from "@/lib/format";

import { asText } from "@/lib/text";

import { liveBlockersOf, liveSwitchError, MASK, secretPatch, statusBadge, type Preflight, type ProviderState, type SecretDraft } from "./model";

const CHOICES: Record<string, readonly string[]> = {
  provider: ["generic", "sim"],
  encryption: ["none", "starttls", "ssl"],
};

interface TemplateRow {
  name: string;
  language: string;
  status: string;
}

export function ProviderCard({ state, webhookUrl }: { state: ProviderState; webhookUrl?: { url: string; note: string } }) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [secrets, setSecrets] = useState<Record<string, SecretDraft>>({});
  const [confirming, setConfirming] = useState(false);
  const [lastTest, setLastTest] = useState<{ ok: boolean; detail: string } | null>(null);
  const [templates, setTemplates] = useState<TemplateRow[] | null>(null);

  // re-seed from the row whenever it changes, so a save by someone else does not leave a stale form
  useEffect(() => {
    setConfig({ ...(state.config ?? {}) });
    setSecrets({});
    // the stored outcome belongs to the row, so a failure explains itself on load — not only after a click
    setLastTest(state.last_test_detail ? { ok: state.last_test_status === "ok", detail: state.last_test_detail } : null);
  }, [state]);

  /* The server is the only thing that knows every provider's live requirements (and the environment
     fallbacks), so the card asks it instead of guessing. `enabled` is guarded: an unconfigured row has no
     provider key, and firing `/settings/integrations/undefined/preflight` is a 422 in the console. */
  const providerKey = asText(state?.provider);
  const preflight = useQuery({
    queryKey: ["settings", "preflight", providerKey],
    queryFn: () => api.get<Preflight>(`/settings/integrations/${providerKey}/preflight`),
    enabled: Boolean(providerKey),
    staleTime: 5_000,
    retry: 0,
  });
  const badge = statusBadge(state?.status);
  const blockers = liveBlockersOf(state, preflight.data);
  const ready = blockers.length === 0;
  const blockerText = blockers
    .map((blocker) =>
      blocker.code === "fields"
        ? t("settings.liveBlockedFields", { fields: blocker.fields.map((field) => t(`settings.field.${field}`, { defaultValue: t(`settings.secret.${field}`, { defaultValue: field }) })).join("، ") })
        : blocker.code === "test"
          ? t("settings.liveBlockedTest")
          : blocker.message,
    )
    .join(" · ");
  const patch = useMemo(() => secretPatch(state.secrets ?? [], secrets), [state.secrets, secrets]);
  const dirty = useMemo(() => {
    const changed = Object.keys(config).some((key) => String(config[key] ?? "") !== String(state.config?.[key as keyof ProviderState["config"]] ?? ""));
    return changed || Object.keys(patch).length > 0;
  }, [config, patch, state.config]);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["settings", "integrations"] });
    await queryClient.invalidateQueries({ queryKey: ["settings", "events"] });
    // the preflight is derived from the row: a green test or a saved field changes the answer
    await queryClient.invalidateQueries({ queryKey: ["settings", "preflight"] });
  }

  const save = useMutation({
    mutationFn: () => api.put<ProviderState>(`/settings/integrations/${state.provider}`, { config, ...(Object.keys(patch).length ? { secrets: patch } : {}) }),
    onSuccess: async (next) => {
      setSecrets({});
      queryClient.setQueryData<ProviderState[]>(["settings", "integrations"], (rows) => (rows ?? []).map((row) => (row.provider === next.provider ? next : row)));
      toast(t("settings.saved"));
      await refresh();
    },
    onError: (error: Error) => toast(error.message, "error"),
  });

  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; detail: string }>(`/settings/integrations/${state.provider}/test`, {}),
    onSuccess: async (result) => {
      setLastTest({ ok: result.ok, detail: result.detail });
      toast(result.ok ? t("settings.testOk") : t("settings.testFailed"), result.ok ? "ok" : "error");
      await refresh();
    },
    onError: async (error: unknown) => {
      const details = (error as { details?: { retry_after_seconds?: number } } | undefined)?.details;
      const seconds = details?.retry_after_seconds;
      toast(seconds ? t("settings.testThrottled", { seconds }) : (error as Error).message, "error");
      await refresh();
    },
  });

  const live = useMutation({
    mutationFn: (isLive: boolean) => api.post<ProviderState>(`/settings/integrations/${state.provider}/live`, { is_live: isLive, confirm: isLive }),
    onSuccess: async (next) => {
      setConfirming(false);
      toast(next.is_live ? t("settings.nowLive") : t("settings.nowSim"));
      await refresh();
    },
    onError: async (error: unknown) => {
      // A 409 here means the screen's picture of the row was stale (a second tab, an env change). Say
      // exactly what the server said — the fields, in Arabic — and re-read the row so the card is correct
      // the moment the box closes rather than leaving a button that keeps failing.
      const { message, fields } = liveSwitchError(error);
      const detail = fields.length ? t("settings.missingFields", { fields: fields.join("، ") }) : asText(message) || t("common.errorBody");
      toast(detail, "error");
      setConfirming(false);
      await refresh();
    },
  });

  const sync = useMutation({
    mutationFn: () => api.post<{ templates: TemplateRow[]; detail: string }>("/settings/integrations/whatsapp/sync-templates", {}),
    onSuccess: (result) => {
      setTemplates(result.templates);
      toast(result.detail);
    },
    onError: (error: Error) => toast(error.message, "error"),
  });

  async function copyUrl() {
    if (!webhookUrl) return;
    try {
      await navigator.clipboard.writeText(webhookUrl.url);
      toast(t("settings.copied"));
    } catch {
      toast(t("settings.copyFailed"), "error");
    }
  }

  return (
    <Card>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-[15px] font-bold text-ink">{t(`settings.provider.${state.provider}`)}</h3>
            {badge.tone ? (
              <Badge tone={badge.tone}>{t(badge.labelKey)}</Badge>
            ) : (
              <span className="inline-flex items-center rounded-pill px-[10px] py-[3px] text-xs font-semibold" style={{ background: "var(--kanban-col)", color: "var(--muted)" }}>
                {t(badge.labelKey)}
              </span>
            )}
          </div>
          <p className="mt-1 text-[12px] text-muted">{t(`settings.provider.${state.provider}Note`)}</p>
        </div>
        <div className="text-end text-[12px] text-muted">
          <div>{state.last_tested_at ? t("settings.lastTest", { when: relativeTime(state.last_tested_at) }) : t("settings.neverTested")}</div>
          {state.updated_at ? <div>{t("settings.updated", { when: relativeTime(state.updated_at) })}</div> : null}
        </div>
      </header>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {Object.keys(state.config ?? {}).map((key) => {
          const original = (state.config as Record<string, unknown>)[key];
          const current = config[key];
          return (
            <label key={key} className="block">
              <span className="mb-1 block text-[12px] font-semibold text-muted">{t(`settings.field.${key}`, { defaultValue: key })}</span>
              {typeof original === "boolean" ? (
                <span className="flex items-center gap-2 rounded-btn border border-line px-3 py-2">
                  <input
                    type="checkbox"
                    name={`config-${key}`}
                    data-testid={`config-${state.provider}-${key}`}
                    className="h-4 w-4 accent-[var(--primary)]"
                    checked={Boolean(current)}
                    onChange={(event) => setConfig((prev) => ({ ...prev, [key]: event.target.checked }))}
                  />
                  {/* the label above the row names the field; a second copy inside it would be noise */}
                </span>
              ) : (
                <input
                  name={`config-${key}`}
                  data-testid={`config-${state.provider}-${key}`}
                  className="w-full rounded-btn border border-line bg-white px-3 py-2 text-[13px] text-ink"
                  value={String(current ?? "")}
                  inputMode={typeof original === "number" ? "numeric" : undefined}
                  list={CHOICES[key] ? `${state.provider}-${key}` : undefined}
                  onChange={(event) => {
                    const raw = event.target.value;
                    setConfig((prev) => ({ ...prev, [key]: typeof original === "number" ? Number(raw) : raw }));
                  }}
                />
              )}
              {CHOICES[key] ? (
                <datalist id={`${state.provider}-${key}`}>
                  {CHOICES[key].map((option) => (
                    <option key={option} value={option} />
                  ))}
                </datalist>
              ) : null}
            </label>
          );
        })}
      </div>

      <div className="mt-4 grid gap-2">
        {(state.secrets ?? []).map((field) => {
          const draft = secrets[field.key] ?? { value: "", remove: false };
          return (
            <div key={field.key} className="flex items-center gap-2">
              <span className="w-[150px] shrink-0 text-[12px] font-semibold text-muted">{t(`settings.secret.${field.key}`, { defaultValue: field.key })}</span>
              <input
                name={`secret-${field.key}`}
                data-testid={`secret-${state.provider}-${field.key}`}
                className="min-w-0 flex-1 rounded-btn border border-line bg-white px-3 py-2 text-[13px] text-ink"
                type="password"
                placeholder={field.set ? MASK : t("settings.secretNotSet")}
                value={draft.value}
                onChange={(event) => setSecrets((prev) => ({ ...prev, [field.key]: { value: event.target.value, remove: false } }))}
              />
              {field.set ? (
                <button
                  type="button"
                  data-testid={`secret-delete-${state.provider}-${field.key}`}
                  className="shrink-0 text-[12px] font-semibold text-[var(--r-ink)] hover:underline"
                  onClick={() => setSecrets((prev) => ({ ...prev, [field.key]: { value: "", remove: !draft.remove } }))}
                >
                  {draft.remove ? t("settings.keepSecret") : t("settings.deleteSecret")}
                </button>
              ) : null}
            </div>
          );
        })}
        <p className="text-[12px] text-muted">{t("settings.secretHint")}</p>
      </div>

      {lastTest ? (
        <div
          className="mt-3 rounded-btn px-3 py-2 text-[12px]"
          style={lastTest.ok ? { background: "var(--g-bg)", color: "var(--g-ink)" } : { background: "var(--r-bg)", color: "var(--r-ink)" }}
          data-testid={`test-result-${state.provider}`}
        >
          {lastTest.detail}
        </div>
      ) : null}

      {!state.is_live && !ready ? (
        <div
          className="mt-3 rounded-btn px-3 py-2 text-[12px]"
          style={{ background: "var(--a-bg)", color: "var(--a-ink)" }}
          data-testid={`live-blockers-${providerKey}`}
          role="status"
        >
          <div className="font-semibold">{t("settings.liveBlockedTitle")}</div>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {blockers.map((blocker) => (
              <li key={blocker.code}>
                {blocker.code === "fields"
                  ? t("settings.liveBlockedFields", {
                      fields: blocker.fields
                        .map((field) => t(`settings.field.${field}`, { defaultValue: t(`settings.secret.${field}`, { defaultValue: field }) }))
                        .join("، "),
                    })
                  : blocker.code === "test"
                    ? t("settings.liveBlockedTest")
                    : blocker.message}
              </li>
            ))}
          </ul>
          {blockers.some((blocker) => blocker.code === "test") ? (
            <button type="button" className="mt-1 font-semibold text-primary hover:underline" onClick={() => test.mutate()}>
              {t("settings.runTestNow")}
            </button>
          ) : null}
        </div>
      ) : null}

      {templates?.length ? (
        <div className="mt-3 rounded-btn bg-[var(--kanban-col)] p-3">
          <div className="mb-1 text-[12px] font-semibold text-muted">{t("settings.templates")}</div>
          <ul className="space-y-1">
            {templates.map((item) => (
              <li key={`${item.name}-${item.language}`} className="flex items-center justify-between gap-2 text-[12px] text-ink">
                <span className="truncate font-medium" dir="ltr">
                  {item.name} · {item.language}
                </span>
                <Badge tone={item.status === "APPROVED" ? "g" : "a"}>{item.status}</Badge>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {webhookUrl ? (
        <div className="mt-3 rounded-btn border border-dashed border-line p-3">
          <div className="text-[12px] font-semibold text-muted">{t("settings.callbackUrl")}</div>
          <div className="mt-1 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate text-[12px] text-ink" dir="ltr" title={webhookUrl.url}>
              {webhookUrl.url}
            </code>
            <Button size="sm" variant="ghost" icon={<Copy size={14} strokeWidth={1.9} />} onClick={() => void copyUrl()}>
              {t("settings.copyUrl")}
            </Button>
          </div>
          <p className="mt-1 text-[12px] text-muted">{webhookUrl.note}</p>
        </div>
      ) : null}

      <footer className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <Button variant="ghost" busy={test.isPending} icon={<PlugZap size={15} strokeWidth={1.9} />} onClick={() => test.mutate()}>
          {t("settings.testConnection")}
        </Button>
        {state.provider === "whatsapp" ? (
          <Button variant="ghost" busy={sync.isPending} icon={<RefreshCw size={15} strokeWidth={1.9} />} onClick={() => sync.mutate()}>
            {t("settings.syncTemplates")}
          </Button>
        ) : null}
        <span className="flex-1" />
        <Button variant="ghost" busy={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>
          {t("common.save")}
        </Button>
        <Button
          variant={state.is_live ? "danger" : "primary"}
          icon={<ShieldAlert size={15} strokeWidth={1.9} />}
          onClick={() => (state.is_live ? live.mutate(false) : setConfirming(true))}
          disabled={live.isPending || (!state.is_live && !ready)}
          title={state.is_live || ready ? undefined : blockerText}
          data-testid={`live-switch-${providerKey}`}
        >
          {state.is_live ? t("settings.backToSim") : t("settings.goLive")}
        </Button>
      </footer>

      {confirming ? (
        <Modal
          title={t("settings.confirmLiveTitle")}
          onClose={() => setConfirming(false)}
          actions={
            <>
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                {t("common.cancel")}
              </Button>
              <Button variant="primary" busy={live.isPending} disabled={!ready} onClick={() => live.mutate(true)}>
                {t("settings.confirmLive")}
              </Button>
            </>
          }
        >
          <p className="text-[13px] text-ink">{t("settings.confirmLiveBody", { provider: t(`settings.provider.${providerKey}`) })}</p>
          {ready ? (
            <p className="mt-2 text-[12px] font-semibold" style={{ color: "var(--g-ink)" }} data-testid="live-ready">
              {t("settings.liveReady")}
            </p>
          ) : (
            <p className="mt-2 text-[12px] text-[var(--a-ink)]" data-testid="live-not-ready">
              {blockerText}
            </p>
          )}
        </Modal>
      ) : null}
    </Card>
  );
}
