"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, FileText, Plus, Trash2 } from "lucide-react";
import { useApp } from "@/components/shared/app-context";
import { BottomNav } from "@/components/shared/bottom-nav";
import { ActionMenu } from "@/components/shared/action-menu";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import {
  PLACEHOLDER_IMAGE,
  handleImageError,
  resolveAssetUrl,
} from "@/lib/asset";
import type { Report } from "@/types";
export function ReportsView() {
  const { reports, navigate, deleteReport, deletingId } = useApp();
  const [pending, setPending] = useState<Report | null>(null);
  return (
    <div className="app-page archive-page">
      <header className="collection-header">
        <div className="brand-mark">旅有所图</div>
        <div className="collection-title-row">
          <h1>旅行报告</h1>
          <Link href="/create?mode=report" className="primary-quiet-button"><Plus size={17} />生成</Link>
        </div>
        <p className="collection-count">{reports.length} 份</p>
      </header>
      <main className="archive-scroll">
        {reports.length ? (
          <div className="persona-archive">
            {reports.map((report, index) => (
              <article key={report.id}>
                <button
                  className="persona-archive-open"
                  onClick={() =>
                    navigate({ page: "report-detail", reportId: report.id })
                  }
                >
                  <div className="persona-archive-photo">
                    <img
                      src={
                        resolveAssetUrl(report.coverImage) || PLACEHOLDER_IMAGE
                      }
                      alt={report.location}
                      onError={handleImageError}
                      loading="lazy"
                    />
                  </div>
                  <div className="persona-archive-copy">
                    <span className="archive-number">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    {report.dateLabel ? <p>{report.dateLabel}</p> : null}
                    <h3>{displayLocation(report.location)}</h3>
                    <span className="text-link">
                      查看报告
                      <ArrowUpRight size={15} />
                    </span>
                  </div>
                </button>
                <div className="archive-menu">
                  <ActionMenu
                    items={[
                      {
                        label: "删除",
                        icon: <Trash2 size={16} />,
                        onClick: () => setPending(report),
                        danger: true,
                      },
                    ]}
                  />
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<FileText size={28} />}
            title="还没有旅行报告"
          >
            <Link href="/create?mode=report" className="primary-action">
              上传照片
            </Link>
          </EmptyState>
        )}
      </main>
      <ConfirmDialog
        open={!!pending}
        title="删除这份旅行报告？"
        description={pending?.location || ""}
        onClose={() => setPending(null)}
        actions={[
          {
            label: deletingId === pending?.id ? "删除中…" : "删除",
            variant: "danger",
            onClick: () => {
              if (pending && deletingId !== pending.id)
                void deleteReport(pending.id).then(() => setPending(null));
            },
          },
          { label: "取消", variant: "ghost", onClick: () => setPending(null) },
        ]}
      />
      <BottomNav />
    </div>
  );
}

function displayLocation(value: string) {
  return value === "未知地点" || value === "未知目的地" ? "未命名旅行" : value
}
