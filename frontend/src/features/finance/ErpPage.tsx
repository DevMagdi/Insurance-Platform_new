/**
 * ERP hub (ADR-031): one accounting home. Period KPIs come only from
 * `GET /finance/spend-by-period` (posted rows); module cards deep-link to the existing screens.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Gauge, HandCoins, Landmark, ReceiptText, Vault } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button, Card, DataTable, Kpi, PageHeader, SectionTitle, StateBlock } from "@/components/ui";
import { ApiError_, api } from "@/lib/api/client";
import { formatDate, formatMoney } from "@/lib/format";
import type { components } from "@/lib/api/schema";

type Spend = components["schemas"]["SpendByPeriodOut"];
export type ErpPeriod = "month" | "quarter" | "semiannual" | "year";
const PERIODS: ErpPeriod[] = ["month", "quarter", "semiannual", "year"];

const MODULES = [
  { to: "/finance/ledger", titleKey: "finance.ledger", descKey: "erp.moduleLedger", icon: <BookOpen size={22} strokeWidth={1.8} /> },
  { to: "/finance/ar", titleKey: "finance.ar", descKey: "erp.moduleAr", icon: <ReceiptText size={22} strokeWidth={1.8} /> },
  { to: "/finance/commissions", titleKey: "finance.commissions", descKey: "erp.moduleCommissions", icon: <HandCoins size={22} strokeWidth={1.8} /> },
  { to: "/finance/cashbox", titleKey: "finance.cashbox", descKey: "erp.moduleCashbox", icon: <Vault size={22} strokeWidth={1.8} /> },
  { to: "/executive", titleKey: "nav.executive", descKey: "erp.moduleExecutive", icon: <Gauge size={22} strokeWidth={1.8} /> },
] as const;

export default function ErpPage() {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<ErpPeriod>("month");
  const spend = useQuery({
    queryKey: ["finance", "spend-by-period", period],
    queryFn: () => api.get<Spend>(`/finance/spend-by-period?period=${period}`),
  });

  return (
    <>
      <PageHeader title={t("erp.title")} subtitle={t("erp.subtitle")} />
      <div className="mb-4 flex flex-wrap items-center gap-2" role="group" aria-label={t("erp.period")}>
        {PERIODS.map((p) => (
          <Button key={p} variant={p === period ? "primary" : "ghost"} aria-pressed={p === period} onClick={() => setPeriod(p)}>
            {t(`erp.periods.${p}`)}
          </Button>
        ))}
        {spend.data ? (
          <span className="text-[13px] text-muted">
            {spend.data.label} · {formatDate(spend.data.start)} ← {formatDate(spend.data.end)}
          </span>
        ) : null}
      </div>

      {spend.isPending ? <StateBlock kind="loading" /> : null}
      {spend.isError ? (
        spend.error instanceof ApiError_ && spend.error.status === 403 ? (
          <StateBlock kind="forbidden" />
        ) : (
          <StateBlock kind="error" action={<Button onClick={() => void spend.refetch()}>{t("common.retry")}</Button>} />
        )
      ) : null}

      {spend.data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Kpi label={t("erp.totalIn")} value={formatMoney(spend.data.total_in)} tone="g" icon={<Landmark size={18} />} />
            <Kpi label={t("erp.totalOut")} value={formatMoney(spend.data.total_out)} tone="a" />
            <Kpi label={t("erp.net")} value={formatMoney(spend.data.net)} tone={spend.data.net >= 0 ? "g" : "r"} />
          </div>
          <Card className="mt-4">
            <SectionTitle>{t("erp.breakdown")}</SectionTitle>
            <DataTable
              columns={[
                { id: "type", head: t("finance.type"), render: (row) => <span className="font-semibold text-ink">{t(`finance.entryType.${row.entry_type}`)}</span> },
                { id: "in", head: t("erp.totalIn"), align: "end", render: (row) => formatMoney(row.in_total) },
                { id: "out", head: t("erp.totalOut"), align: "end", render: (row) => formatMoney(row.out_total) },
                { id: "net", head: t("erp.net"), align: "end", render: (row) => formatMoney(row.net) },
              ]}
              rows={spend.data.by_type ?? []}
              keyOf={(row) => row.entry_type}
              empty={<StateBlock kind="empty" title={t("erp.empty")} />}
            />
          </Card>
        </>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {MODULES.map((m) => (
          <Link key={m.to} to={m.to} className="block">
            <Card className="h-full transition hover:border-primary">
              <div className="mb-2 text-primary">{m.icon}</div>
              <div className="text-[15px] font-bold text-ink">{t(m.titleKey)}</div>
              <div className="mt-1 text-[13px] text-muted">{t(m.descKey)}</div>
            </Card>
          </Link>
        ))}
      </div>
    </>
  );
}
