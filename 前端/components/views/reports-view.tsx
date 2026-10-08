"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, FileText, Plus, Trash2 } from "lucide-react";
import { useApp } from "@/components/shared/app-context";
import { BottomNav } from "@/components/shared/bottom-nav";
import { ActionMenu } from "@/components/shared/action-menu";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { CollectionHeader } from "@/components/shared/collection-header";
import {
  PLACEHOLDER_IMAGE,
  handleImageError,
  resolveAssetUrl,
} from "@/lib/asset";
import { displayPlace } from "@/lib/place";
import type { Report } from "@/types";
export function ReportsView() {
  const { reports, navigate, deleteReport, deletingId } = useApp();
  const [pending, setPending] = useState<Report | null>(null);
  return (
    <div className="app-page archive-page">
      <CollectionHeader
        section="报告"
        title="旅行人格报告"
        description="从镜头里的风景，认识旅行中的自己。"
        count={reports.length ? `${reports.length} 份报告` : undefined}
        action={<Link href="/create?mode=report" className="primary-quiet-button"><Plus size={17} aria-hidden />生成报告</Link>}
      />
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
                    <h3>{report.profileData?.archetypeName || displayPlace(report.location, report.personalitySummary)}</h3>
                    <span className="lg-list-route">{listSubtitle(report)}</span>
                    <span className="text-link">
                      查看旅格
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
            title="还没有旅行人格报告"
            description="上传至少 10 张旅行照片，看看你这次旅行的独特气质。"
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
        description={pending ? (pending.profileData?.journey?.title || displayPlace(pending.location, pending.personalitySummary)) : ""}
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

function listSubtitle(report: Report) {
  const profile = report.profileData
  const journey = profile?.journey
  const code = profile?.axes?.length ? profile.personaCode : ""
  const place = journey?.title || displayPlace(report.location, report.personalitySummary)
  return [code, place].filter(Boolean).join(" · ")
}
