"use client";
import type { ReactNode } from "react";
import { ChevronLeft } from "lucide-react";
import { useApp } from "@/components/shared/app-context";
export function TopBar({
  title,
  subtitle,
  onBack,
  right,
  showUserBadge = false,
  showBack = true,
  backHref,
  backLabel = "返回",
}: {
  title?: string;
  subtitle?: string;
  onBack?: () => void;
  right?: ReactNode;
  showUserBadge?: boolean;
  showBack?: boolean;
  backHref?: string;
  backLabel?: string;
}) {
  const { goBack, goBackTo } = useApp();
  return (
    <header className="top-bar">
      <div className="top-bar-main">
        {showBack ? (
          <button
            type="button"
            onClick={onBack ?? (() => backHref ? goBackTo(backHref) : goBack())}
            className="icon-button"
            aria-label={backLabel}
          >
            <ChevronLeft size={23} aria-hidden />
          </button>
        ) : null}
        <div className="top-bar-title">
          <h1>{title}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {showUserBadge ? <span className="top-bar-spacer" /> : null}
      </div>
      {right && <div className="top-bar-actions">{right}</div>}
    </header>
  );
}
