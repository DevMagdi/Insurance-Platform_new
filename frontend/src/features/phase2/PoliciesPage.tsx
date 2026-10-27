/**
 * Screen 12 — policies, payment plan and commissions (Phase 2). Shipped in full but gated
 * by `phase2.enabled`, so the data path is real as soon as the flag is on.
 */
import { useQuery } from "@tanstack/react-query";
import { Banknote, CalendarClock, FileCheck2, TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Modal } from "@/components/Modal";
import { Badge, Button, Card, DataTable, PageHeader, SectionTitle, StateBlock } from "@/components/ui";
import { api } from "@/lib/api/client";
import { daysUntil, formatDate, formatMoney, formatNumber } from "@/lib/format";
import type { AnyPage, InstallmentPlan } from "@/lib/api/views";
import type { components } from "@/lib/api/schema";
import { Phase2Screen } from "./phase2Gate";

type PolicyRow = components["schemas"]["PolicyOut"];
type PolicyKpis = components["schemas"]["PolicyKpisOut"];

export default function PoliciesPage() {
  return (
    <Phase2Screen>
      <PoliciesContent />
    </Phase2Screen>
  );
}

function PoliciesContent() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [openPlan, setOpenPlan] = useState<string | null>(null);

  const list = useQuery({ queryKey: ["policies"], queryFn: () => api.get<AnyPage>("/policies", { page_size: 50 }) });
  const kpis = useQuery({ queryKey: ["policies", "kpis"], queryFn: () => api.get<PolicyKpis>("/policies/kpis") });
  const rows = (list.data?.items ?? []) as PolicyRow[];

  return (
    <>
      <PageHeader
        title={t("phase2.policies")}
        subtitle={t("phase2.policiesSubtitle")}
        actions={
          <Button variant="primary" onClick={() => navigate("/issuing")}>
            {t("phase2.issuePolicy")}
          </Button>
        }
      />

      <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile
          label={t("phase2.kpiActive")}
          value={formatNumber(kpis.data?.active ?? 0)}
          hint={t("phase2.kpiActiveHint", { n: formatNumber(kpis.data?.expiring_90d ?? 0) })}
          tone="g"
          icon={<FileCheck2 size={18} strokeWidth={1.8} />}
        />
        <Tile
          label={t("phase2.kpiMonth")}
          value={formatNumber(kpis.data?.installments_this_month ?? 0)}
          hint={t("phase2.kpiMonthHint", { n: formatNumber(kpis.data?.installments_this_month ?? 0) })}
          tone="b"
          icon={<CalendarClock size={18} strokeWidth={1.8} />}
        />
        <Tile
          label={t("phase2.kpiLate")}
          value={formatNumber(kpis.data?.late_installments ?? 0)}
          hint={t("phase2.kpiLateHint")}
          tone={Number(kpis.data?.late_installments ?? 0) > 0 ? "r" : "g"}
          icon={<TriangleAlert size={18} strokeWidth={1.8} />}
        />
        <Tile
          label={t("phase2.kpiCommission")}
          value={kpis.data?.expected_commission != null ? formatMoney(kpis.data.expected_commission, kpis.data.currency) : "—"}
          hint={t("phase2.kpiCommissionHint")}
          tone="t"
          icon={<Banknote size={18} strokeWidth={1.8} />}
        />
      </div>

      <Card padded={false}>
        <div className="px-[20px] pt-[18px]">
          <SectionTitle>{t("phase2.colPolicy")}</SectionTitle>
        </div>
        <div className="px-[20px] pb-[18px]">
          {list.isPending ? (
            <StateBlock kind="loading" />
          ) : list.isError ? (
            <StateBlock kind="error" action={<Button onClick={() => void list.refetch()}>{t("common.retry")}</Button>} />
          ) : (
            <DataTable
              rows={rows}
              keyOf={(row) => String(row.id)}
              onRowClick={(row) => setOpenPlan(String(row.id))}
              empty={<StateBlock kind="empty" title={t("phase2.policies")} />}
              columns={[
                {
                  id: "policy",
                  head: t("phase2.colPolicy"),
                  width: 170,
                  render: (row) => (
                    <div>
                      <p className="text-[13px] font-bold text-ink">{row.policy_no ?? "—"}</p>
                      <p className="text-[11.5px] text-muted">{row.insurer?.name ?? "—"}</p>
                    </div>
                  ),
                },
                { id: "client", head: t("phase2.colClient"), width: 160, render: () => <span className="text-[12.5px] text-muted">—</span> },
                { id: "coverage", head: t("phase2.colCoverage"), width: 150, render: (row) => row.insurance_type?.name ?? "—" },
                { id: "premium", head: t("phase2.colPremium"), width: 140, align: "end", render: (row) => formatMoney(row.premium_amount, row.currency) },
                { id: "payment", head: t("phase2.colPayment"), width: 110, render: (row) => row.payment_plan ?? "—" },
                {
                  id: "next",
                  head: t("phase2.colNext"),
                  width: 150,
                  render: (row) => {
                    const left = daysUntil(row.end_date ?? null);
                    if (left === null) return "—";
                    return (
                      <span className={`text-[12.5px] font-semibold ${left <= 90 ? "text-[var(--a-ink)]" : "text-muted"}`}>
                        {t("clients.renewalInDays", { n: formatNumber(left) })} · {formatDate(row.end_date)}
                      </span>
                    );
                  },
                },
                {
                  id: "status",
                  head: t("phase2.colStatus"),
                  width: 110,
                  align: "end",
                  render: (row) => <Badge tone={row.status === "issued" ? "g" : row.status === "cancelled" ? "r" : "a"}>{t(`phase2.${row.status}`, { defaultValue: row.status })}</Badge>,
                },
              ]}
            />
          )}
        </div>
      </Card>

      {openPlan ? <InstallmentsDialog policyId={openPlan} onClose={() => setOpenPlan(null)} /> : null}
    </>
  );
}

function InstallmentsDialog({ policyId, onClose }: { policyId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const plan = useQuery({
    queryKey: ["policies", policyId, "installments"],
    queryFn: () => api.get<InstallmentPlan>(`/policies/${policyId}/installments`),
  });
  const today = new Date();
  return (
    <Modal
      title={t("phase2.installments", { policy: plan.data?.policy.policy_no ?? "—" })}
      onClose={onClose}
      width={560}
      actions={
        <Button variant="primary" onClick={onClose}>
          {t("common.close")}
        </Button>
      }
    >
      {plan.isPending ? (
        <StateBlock kind="loading" />
      ) : plan.isError ? (
        <StateBlock kind="error" body={t("common.errorBody")} />
      ) : (
        <>
          <p className="text-[12.5px] text-muted">{t("phase2.autoInstallments")}</p>
          <ul className="mt-3 max-h-[320px] space-y-1 overflow-auto">
            {(plan.data?.items ?? []).map((row) => {
              const due = row.due_date ? new Date(`${row.due_date}T00:00:00Z`) : null;
              const late = row.status !== "paid" && due !== null && due < today;
              const soon = !late && row.status !== "paid" && due !== null && due.getTime() - today.getTime() < 30 * 86_400_000;
              return (
                <li key={String(row.id)} className="row-line flex items-center justify-between gap-3 py-2 text-[13px]">
                  <span className="tabular-nums text-muted">
                    {formatNumber(row.sequence_no ?? 0)} · {formatDate(row.due_date)}
                  </span>
                  <span className="font-semibold text-ink tabular-nums">{formatMoney(row.amount)}</span>
                  <Badge tone={row.status === "paid" ? "g" : late ? "r" : soon ? "a" : "b"}>
                    {row.status === "paid"
                      ? t("phase2.paid")
                      : late
                        ? t("phase2.late", { n: formatNumber(Math.round((today.getTime() - (due?.getTime() ?? 0)) / 86_400_000)) })
                        : soon
                          ? t("phase2.soon")
                          : t("phase2.upcoming")}
                  </Badge>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Modal>
  );
}

function Tile({ label, value, hint, tone, icon }: { label: string; value: string; hint: string; tone: "b" | "g" | "a" | "r" | "t"; icon: ReactNode }) {
  return (
    <Card className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="text-[13px] text-muted">{label}</div>
        <div className="mt-1.5 text-kpi font-bold tabular-nums text-ink">{value}</div>
        <div className="mt-1 text-[12px] text-muted">{hint}</div>
      </div>
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px]" style={{ background: `var(--${tone}-bg)`, color: `var(--${tone}-ink)` }}>
        {icon}
      </span>
    </Card>
  );
}
