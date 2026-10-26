/** Small accessible dialog used by the confirmations (convert, lost, redistribute, import). */
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Card } from "@/components/ui";

export function Modal({
  title,
  children,
  actions,
  onClose,
  width = 480,
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  onClose: () => void;
  width?: number;
}) {
  const { t } = useTranslation();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 grid place-items-center bg-[rgba(16,24,40,.5)] p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <Card className="w-full" style={{ maxWidth: width }}>
        <header className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-card font-semibold text-ink">{title}</h2>
          <button
            type="button"
            className="grid h-8 w-8 place-items-center rounded-full text-muted transition-colors duration-150 hover:bg-[#F3F4F9] hover:text-ink"
            onClick={onClose}
            aria-label={t("common.close")}
          >
            <X size={16} strokeWidth={2} />
          </button>
        </header>
        {children}
        {actions ? <footer className="mt-5 flex items-center justify-end gap-2">{actions}</footer> : null}
      </Card>
    </div>
  );
}
