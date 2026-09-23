"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useApp } from "@/components/shared/app-context";
import { TopBar } from "@/components/shared/top-bar";
import { ItineraryDetail } from "@/components/shared/itinerary-detail";
import { EmptyState } from "@/components/shared/empty-state";
import { ArrowRight, Compass } from "lucide-react";

export function HistoryDetailView() {
  const [exportTarget, setExportTarget] = useState<HTMLDivElement | null>(null);
  const searchParams = useSearchParams();
  const { plans, beginEditPlan, navigate } = useApp();
  const plan = plans.find((p) => p.id === searchParams.get("planId"));
  const sourceTripId = searchParams.get("tripId");
  const backHref = searchParams.get("from") === "trip" && sourceTripId
    ? `/trips/detail?tripId=${encodeURIComponent(sourceTripId)}`
    : "/planning/history";
  const backLabel = sourceTripId ? "返回这次旅行" : "返回已保存行程";

  if (!plan) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <TopBar title="行程" showUserBadge={false} backHref={backHref} backLabel={backLabel} />
        <div className="min-h-0 flex-1 overflow-y-auto no-scrollbar">
          <EmptyState
            icon={<Compass className="size-7" aria-hidden />}
            title="行程不存在"
            description="这份行程可能已被删除。"
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <TopBar
        title={plan.location}
        subtitle={plan.dateLabel}
        showUserBadge={false}
        backHref={backHref}
        backLabel={backLabel}
        right={<div ref={setExportTarget} className="history-export-slot" />}
      />
      <div className="min-h-0 flex-1 overflow-y-auto no-scrollbar">
        {plan.tripId ? <div className="detail-trip-link">
          <Link href={`/trips/detail?tripId=${encodeURIComponent(plan.tripId)}&from=history&sourceId=${encodeURIComponent(plan.id)}`}>查看这次旅行<ArrowRight size={15} /></Link>
        </div> : null}
        {plan.itineraryData.planning_snapshot && (plan.itineraryData.memory_context?.selected.length ?? 0) > 0 ? <div className="planning-memory-compare">
          <p>这份行程保存了当时的确认需求。核对后可重新规划对照，原行程不会被覆盖。</p>
          <button type="button" onClick={() => {
            beginEditPlan(plan);
            navigate({ page: "planning", planId: plan.id });
          }}>按保存时需求核对并对照</button>
        </div> : null}
        <ItineraryDetail
          data={plan.itineraryData}
          exportTarget={exportTarget}
        />
      </div>
    </div>
  );
}
