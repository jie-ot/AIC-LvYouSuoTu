"use client";
import { useState } from "react";
import { ArrowUpRight, Route, Pencil, Trash2 } from "lucide-react";
import { useApp } from "@/components/shared/app-context";
import { TopBar } from "@/components/shared/top-bar";
import { ActionMenu } from "@/components/shared/action-menu";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import type { Plan } from "@/types";
export function HistoryView() {
  const {
    plans,
    navigate,
    beginNewPlan,
    beginEditPlan,
    deletePlan,
    deletingId,
  } = useApp();
  const [pending, setPending] = useState<Plan | null>(null);
  const newPlan = () => {
    beginNewPlan();
    navigate({ page: "planning" });
  };
  return (
    <div className="archive-page">
      <TopBar title="已保存行程" showUserBadge={false} backHref="/planning" backLabel="返回行程规划" />
      <div className="archive-scroll">
        <header className="archive-summary">
          <Route size={23} strokeWidth={1.3} />
          <span>
            <b>{plans.length}</b> 份行程
          </span>
          <button onClick={newPlan}>
            新建行程
            <ArrowUpRight size={16} />
          </button>
        </header>
        {plans.length ? (
          <div className="plan-archive">
            {plans.map((plan, index) => (
              <article key={plan.id}>
                <span className="plan-archive-index">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <button
                  className="plan-archive-open"
                  onClick={() =>
                    navigate({ page: "history-detail", planId: plan.id })
                  }
                >
                  <span className="eyebrow">{plan.dateLabel}</span>
                  <h3>{plan.location}</h3>
                  <p>
                    {plan.itineraryData.itinerary
                      .map((d) => d.title)
                      .filter(Boolean)
                      .slice(0, 2)
                      .join(" / ")}
                  </p>
                  <div>
                    <span>{plan.itineraryData.itinerary.length} 天行程</span>
                    <span>
                      {plan.itineraryData.food_recommendations.length} 项美食
                    </span>
                    <ArrowUpRight size={18} />
                  </div>
                </button>
                <div className="archive-menu">
                  <ActionMenu
                    items={[
                      {
                        label: "重新编辑",
                        icon: <Pencil size={16} />,
                        onClick: () => {
                          beginEditPlan(plan);
                          navigate({ page: "planning", planId: plan.id });
                        },
                      },
                      {
                        label: "删除",
                        icon: <Trash2 size={16} />,
                        danger: true,
                        onClick: () => setPending(plan),
                      },
                    ]}
                  />
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<Route size={28} />}
            title="还没有保存的行程"
          >
            <button className="primary-action" onClick={newPlan}>
              规划旅行
            </button>
          </EmptyState>
        )}
      </div>
      <ConfirmDialog
        open={!!pending}
        title="删除这份行程？"
        description={pending?.location || ""}
        onClose={() => setPending(null)}
        actions={[
          {
            label: deletingId === pending?.id ? "删除中…" : "删除",
            variant: "danger",
            onClick: () => {
              if (pending && deletingId !== pending.id)
                void deletePlan(pending.id).then(() => setPending(null));
            },
          },
          { label: "取消", variant: "ghost", onClick: () => setPending(null) },
        ]}
      />
    </div>
  );
}
