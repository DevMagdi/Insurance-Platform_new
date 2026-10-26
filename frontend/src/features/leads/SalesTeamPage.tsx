/**
 * Screen 6 — manager view of the sales team: one card per rep with a 10px stage bar,
 * a high-load warning above 20 open leads, and an unassigned pool that can be redistributed.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, TriangleAlert, UserPlus } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Modal } from "@/components/Modal";
import { Avatar, Badge, Button, Card, PageHeader, SectionTitle, StateBlock } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api/client";
import { formatNumber, formatPercent } from "@/lib/format";
import type { Lead, RepWorkload } from "@/lib/api/views";

const STAGE_ORDER = ["new", "contacted", "meeting_scheduled", "quote_sent", "negotiation"] as const;
const STAGE_COLOR: Record<string, string> = {
  new: "var(--b-ink)",
  contacted: "var(--primary)",
  meeting_scheduled: "var(--a-ink)",
  quote_sent: "var(--t-ink)",
  negotiation: "var(--g-ink)",
};

const HIGH_LOAD = 20;

export default function SalesTeamPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [redistributing, setRedistributing] = useState(false);

  const team = useQuery({ queryKey: ["sales", "team"], queryFn: () => api.get<RepWorkload[]>("/sales/team") });
  const unassigned = useQuery({
    queryKey: ["leads", "unassigned"],
    queryFn: () => api.get<{ items: Lead[]; total: number }>("/leads", { unassigned: true, page_size: 50 }),
  });

  const assign = useMutation({
    mutationFn: async (input: { leadIds: string[]; repId: string }) => {
      for (const id of input.leadIds) {
        await api.post(`/leads/${id}/assign`, { assigned_to: input.repId });
      }
      return input.leadIds.length;
    },
    onSuccess: (count) => {
      void queryClient.invalidateQueries({ queryKey: ["leads"] });
      void queryClient.invalidateQueries({ queryKey: ["sales"] });
      setRedistributing(false);
      toast(t("leads.assignSaved"));
      if (count === 0) toast(t("leads.empty"), "warn");
    },
    onError: () => toast(t("common.errorBody"), "error"),
  });

  if (team.isPending) return <StateBlock kind="loading" />;
  if (team.isError) {
    return <StateBlock kind="error" action={<Button onClick={() => void team.refetch()}>{t("common.retry")}</Button>} />;
  }
  const rows = team.data ?? [];
  const totals = rows.reduce(
    (acc, row) => ({ open: acc.open + row.open_leads, won: acc.won + row.won, meetings: acc.meetings + row.meetings }),
    { open: 0, won: 0, meetings: 0 },
  );

  return (
    <>
      <PageHeader
        title={t("leads.team")}
        subtitle={t("leads.teamSubtitle")}
        actions={
          <Button variant="primary" icon={<UserPlus size={16} strokeWidth={1.8} />} onClick={() => navigate("/leads/new")}>
            {t("leads.newLead")}
          </Button>
        }
      />

      <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card className="!py-4">
          <div className="text-[12.5px] text-muted">{t("leads.allLeads")}</div>
          <div className="mt-1 text-[26px] font-bold tabular-nums text-ink">{formatNumber(totals.open)}</div>
        </Card>
        <Card className="!py-4">
          <div className="text-[12.5px] text-muted">{t("leads.kpiMeetings")}</div>
          <div className="mt-1 text-[26px] font-bold tabular-nums text-ink">{formatNumber(totals.meetings)}</div>
        </Card>
        <Card className="!py-4">
          <div className="text-[12.5px] text-muted">{t("leads.kpiConverted")}</div>
          <div className="mt-1 text-[26px] font-bold tabular-nums text-ink">{formatNumber(totals.won)}</div>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-4">
        {rows.map((rep) => {
          const high = rep.open_leads > HIGH_LOAD;
          return (
            <Card key={rep.rep_id} style={high ? { background: "var(--row-warn)" } : undefined}>
              <div className="flex items-start gap-3">
                <Avatar name={rep.name} size={38} />
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-[14px] font-bold text-ink">{rep.name}</h3>
                  <p className="mt-0.5 text-[12px] text-muted">
                    {formatNumber(rep.open_leads)} {t("leads.allLeads")} · {formatPercent(rep.conversion_rate ?? null)} {t("leads.conversion")}
                  </p>
                </div>
                {high ? <Badge tone="a">{t("leads.loadHigh")}</Badge> : <Badge tone="g">{t("leads.loadBalanced")}</Badge>}
              </div>

              <div className="mt-4 flex h-[10px] w-full overflow-hidden rounded-pill bg-white">
                {STAGE_ORDER.map((stage) => {
                  const pct = rep.stages_pct?.[stage] ?? 0;
                  return (
                    <span
                      key={stage}
                      title={`${t(`leadStatus.${stage}`)} · ${rep.stages?.[stage] ?? 0}`}
                      style={{ width: `${pct}%`, background: STAGE_COLOR[stage] }}
                    />
                  );
                })}
              </div>

              <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
                <Stat label={t("leads.colMeeting")} value={rep.meetings} icon={<CalendarCheck size={13} strokeWidth={1.8} />} />
                <Stat label={t("leads.colWon")} value={rep.won} />
                <Stat label={t("leads.insured_count")} value={rep.open_leads} />
              </dl>

              {high ? (
                <p className="mt-3 flex items-center gap-1.5 text-[12px] font-semibold text-[var(--a-ink)]">
                  <TriangleAlert size={13} strokeWidth={1.8} />
                  {t("leads.overloaded")}
                </p>
              ) : null}

              <button type="button" className="mt-3 text-[12.5px] font-semibold text-primary hover:underline" onClick={() => navigate(`/leads?rep=${rep.rep_id}`)}>
                {t("common.view")}
              </button>
            </Card>
          );
        })}
      </div>

      <Card className="mt-5" style={{ background: "var(--row-warn)" }} padded={false}>
        <div className="px-[20px] py-[18px]">
          <SectionTitle
            action={
              <Button variant="primary" disabled={(unassigned.data?.total ?? 0) === 0} onClick={() => setRedistributing(true)}>
                {t("leads.redistribute")}
              </Button>
            }
          >
            {t("leads.unassignedTitle")}
          </SectionTitle>
          {unassigned.isPending ? (
            <StateBlock kind="loading" />
          ) : (unassigned.data?.items ?? []).length === 0 ? (
            <p className="text-[13px] text-muted">{t("leads.empty")}</p>
          ) : (
            <ul className="space-y-2">
              {(unassigned.data?.items ?? []).slice(0, 6).map((lead) => (
                <li key={lead.id} className="flex items-center justify-between gap-3 border-t border-line pt-2 text-[13px]">
                  <button type="button" className="truncate font-semibold text-ink hover:text-primary" onClick={() => navigate(`/leads/${lead.id}`)}>
                    {lead.name}
                  </button>
                  <span className="shrink-0 text-muted">{t(`leadStatus.${lead.status}`)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      {redistributing ? (
        <RedistributeDialog
          reps={rows}
          leads={(unassigned.data?.items ?? []).map((lead) => lead.id)}
          busy={assign.isPending}
          onClose={() => setRedistributing(false)}
          onSubmit={(repId) => assign.mutate({ leadIds: (unassigned.data?.items ?? []).map((lead) => lead.id), repId })}
        />
      ) : null}
    </>
  );
}

function Stat({ label, value, icon }: { label: string; value: number | null | undefined; icon?: ReactNode }) {
  return (
    <div className="rounded-btn bg-white py-2">
      <dd className="text-[17px] font-bold tabular-nums text-ink">{formatNumber(value ?? 0)}</dd>
      <dt className="mt-0.5 flex items-center justify-center gap-1 text-[11px] text-muted">
        {icon}
        {label}
      </dt>
    </div>
  );
}

function RedistributeDialog({
  reps,
  leads,
  onSubmit,
  onClose,
  busy,
}: {
  reps: RepWorkload[];
  leads: string[];
  onSubmit: (repId: string) => void;
  onClose: () => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  const [repId, setRepId] = useState("");
  return (
    <Modal
      title={t("leads.redistribute")}
      onClose={onClose}
      actions={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" busy={busy} disabled={repId.length === 0 || leads.length === 0} onClick={() => onSubmit(repId)}>
            {t("common.confirm")}
          </Button>
        </>
      }
    >
      <p className="text-[13px] text-muted">
        {t("leads.redistributeBody")} · {formatNumber(leads.length)} {t("common.rows")}
      </p>
      <label className="label mt-4" htmlFor="rep-pick">
        {t("leads.rep")}
      </label>
      <select id="rep-pick" className="field" value={repId} onChange={(event) => setRepId(event.target.value)}>
        <option value="">{t("common.none")}</option>
        {reps.map((rep) => (
          <option key={rep.rep_id} value={rep.rep_id}>
            {rep.name} — {formatNumber(rep.open_leads)}
          </option>
        ))}
      </select>
    </Modal>
  );
}
