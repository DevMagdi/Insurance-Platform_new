import {
  BarChart3,
  ClipboardList,
  FolderOpen,
  Inbox,
  KanbanSquare,
  LayoutDashboard,
  LogOut,
  Settings,
  Users,
} from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Avatar, SearchInput } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { changeLanguage } from "@/lib/i18n";

interface NavItem {
  to: string;
  labelKey: string;
  icon: ReactNode;
  perm?: string;
  badge?: string;
}

const NAV: NavItem[] = [
  { to: "/dashboard", labelKey: "nav.dashboard", icon: <LayoutDashboard size={20} strokeWidth={1.8} /> },
  { to: "/inbox", labelKey: "nav.inbox", icon: <Inbox size={20} strokeWidth={1.8} />, badge: "24" },
  { to: "/leads", labelKey: "nav.leads", icon: <KanbanSquare size={20} strokeWidth={1.8} /> },
  { to: "/clients", labelKey: "nav.clients", icon: <FolderOpen size={20} strokeWidth={1.8} /> },
  { to: "/sales-team", labelKey: "leads.team", icon: <Users size={20} strokeWidth={1.8} /> },
  { to: "/policies", labelKey: "nav.policies", icon: <ClipboardList size={20} strokeWidth={1.8} />, perm: "policies.view" },
  { to: "/reports", labelKey: "nav.reports", icon: <BarChart3 size={20} strokeWidth={1.8} />, perm: "reports.view" },
  { to: "/users", labelKey: "nav.settings", icon: <Settings size={20} strokeWidth={1.8} />, perm: "users.manage" },
];

export function StaffShell({ children }: { children: ReactNode }) {
  const { t, i18n } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [globalTerm, setGlobalTerm] = useState("");
  const [signingOut, setSigningOut] = useState(false);

  const items = NAV.filter((item) => !item.perm || user?.permissions?.includes(item.perm));

  return (
    <div className="flex min-h-screen bg-bg">
      <aside className="sticky top-0 h-screen w-[264px] shrink-0 bg-sidebar px-[12px] py-[18px]">
        <div className="mb-[20px] flex items-center gap-2.5 px-2">
          <span className="grid h-[34px] w-[34px] place-items-center rounded-[10px] text-[15px] font-bold text-white" style={{ background: "var(--primary)" }}>
            و
          </span>
          <div className="min-w-0">
            <div className="truncate text-[15px] font-bold text-white">{t("common.appName")}</div>
          </div>
        </div>

        <nav className="flex flex-col gap-1" aria-label="main">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-btn px-3 py-[11px] text-[14px] font-semibold transition ${
                  isActive ? "bg-[var(--sidebar-active)] text-white" : "text-[var(--sidebar-text)] hover:bg-white/5 hover:text-white"
                }`
              }
            >
              {item.icon}
              <span className="flex-1 truncate">{t(item.labelKey)}</span>
              {item.badge ? (
                <span className="rounded-pill bg-primary px-2 py-[2px] text-[11px] font-bold text-white">{item.badge}</span>
              ) : null}
            </NavLink>
          ))}
        </nav>

        <div className="mt-[18px] border-t border-white/10 px-2 pt-3">
          <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-white/40">{t("users.scope")}</div>
          <div className="text-[12px] text-[var(--sidebar-text)]">
            {user?.scope_mode === "all" ? t("users.allClients") : t("users.scoped")}
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-[54px] items-center justify-between gap-4 border-b border-line bg-card px-[24px]">
          <div className="min-w-0 text-[13px] text-muted">{t("dashboard.subtitle")}</div>
          <div className="flex flex-1 items-center justify-end gap-3">
            {/* The sheet's header field: typing here filters the shared inbox queue */}
            <form
              role="search"
              className="hidden lg:block"
              onSubmit={(event) => {
                event.preventDefault();
                const term = globalTerm.trim();
                if (term) navigate(`/inbox?q=${encodeURIComponent(term)}`);
              }}
            >
              <SearchInput value={globalTerm} onChange={setGlobalTerm} placeholder={t("common.search")} />
            </form>
            <button
              type="button"
              className="rounded-btn px-2.5 py-1.5 text-[13px] font-semibold text-muted transition hover:bg-[#F1F2F8] hover:text-ink"
              onClick={() => void changeLanguage(i18n.language === "ar" ? "en" : "ar")}
              aria-label="language"
            >
              {i18n.language === "ar" ? "EN" : "ع"}
            </button>
            <Avatar name={user?.full_name ?? "?"} size={30} />
            <span className="hidden text-[13px] font-semibold text-ink sm:block">{user?.full_name}</span>
            <button
              type="button"
              className="flex items-center gap-1.5 text-[13px] font-semibold text-muted transition hover:text-[var(--r-ink)]"
              disabled={signingOut}
              onClick={async () => {
                setSigningOut(true);
                try {
                  await api.post("/portal/sign-out").catch(() => undefined);
                  await logout();
                  navigate("/login", { replace: true });
                } finally {
                  setSigningOut(false);
                }
              }}
            >
              <LogOut size={16} strokeWidth={1.8} />
              <span className="hidden md:inline">{t("portal.signOut")}</span>
            </button>
          </div>
        </header>

        <main className="content-pad min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
