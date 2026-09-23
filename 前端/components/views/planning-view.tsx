"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useApp } from "@/components/shared/app-context";
import { TopBar } from "@/components/shared/top-bar";
import { ItineraryDetail } from "@/components/shared/itinerary-detail";
import {
  PlanningConversation,
  type PlanningConversationMessage,
} from "@/components/shared/planning-conversation";
import { PlanningProgress } from "@/components/shared/planning-progress";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { BottomNav } from "@/components/shared/bottom-nav";
import { usePlanningProgress } from "@/lib/use-planning-progress";
import { planWithAI } from "@/lib/api";
import { Brain, History, Save, RotateCcw, Send } from "lucide-react";
import type {
  ItineraryData,
  PlanningBrief,
  PlanningChecklistItem,
  PlanningModel,
} from "@/types";

const DEFAULT_PLANNING_MODEL: PlanningModel = "deepseek-v4-flash";

const INITIAL_MESSAGES: PlanningConversationMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content: "想去哪里，准备待几天？",
  },
];

export function PlanningView() {
  const search = useSearchParams();
  const requestedTripId = search.get("tripId");
  const {
    navigate,
    goBackTo,
    registerBackHandler,
    toast,
    toastError,
    toastCode,
    draftItineraryData,
    editingPlanId,
    hasUnsavedDraft,
    planning,
    planningProgressToken,
    planningTurn,
    planRefine,
    planningSeed,
    clearPlanningSeed,
    beginNewPlan,
    discardDraft,
    saving,
    savePlan,
    planningTripId,
  } = useApp();

  const [exportTarget, setExportTarget] = useState<HTMLDivElement | null>(null);
  const [prompt, setPrompt] = useState(() => planningSeed?.text ?? "");
  const [refinePrompt, setRefinePrompt] = useState("");
  const [saved, setSaved] = useState(false);
  const [useMemory, setUseMemory] = useState(true);
  const [comparison, setComparison] = useState<ItineraryData | null>(null);
  const [comparisonBefore, setComparisonBefore] = useState<ItineraryData | null>(null);
  const [comparisonLabel, setComparisonLabel] = useState("");
  const [comparing, setComparing] = useState(false);
  const [chatMessages, setChatMessages] =
    useState<PlanningConversationMessage[]>(INITIAL_MESSAGES);
  const [brief, setBrief] = useState<PlanningBrief | null>(null);
  const [checklist, setChecklist] = useState<PlanningChecklistItem[]>([]);
  const [conversationPhase, setConversationPhase] = useState<
    "collecting" | "confirming"
  >("collecting");
  const selectedModel = DEFAULT_PLANNING_MODEL;
  const [generationRequested, setGenerationRequested] = useState(false);
  const [confirmationToken, setConfirmationToken] = useState<string | null>(
    null,
  );
  const [confirmedSavedSnapshotKey, setConfirmedSavedSnapshotKey] = useState<string | null>(null);
  const [seedSource, setSeedSource] = useState<string | null>(
    () => planningSeed?.sourceLabel ?? null,
  );
  const [seedReturnHref] = useState<string | null>(
    () => planningSeed?.returnHref ?? null,
  );
  const confirmationInFlight = useRef(false);
  const comparisonEpoch = useRef(0);
  const backHref = requestedTripId
    ? `/trips/detail?tripId=${encodeURIComponent(requestedTripId)}`
    : editingPlanId
      ? "/planning/history"
      : seedReturnHref ?? "/";
  // 未保存草稿返回拦截（规范 §10.5）
  const [showLeaveConfirm, setShowLeaveConfirm] = useState(false);
  const pendingLeave = useRef<(() => void) | null>(null);
  const initializedTrip = useRef(false);

  // 继续编辑的草稿载入已在「历史规划」点击时完成（beginEditPlan + URL 导航），此处仅消费 context

  const phase: "conversation" | "generating" | "result" =
    planning && (generationRequested || draftItineraryData)
      ? "generating"
      : draftItineraryData
        ? "result"
        : "conversation";
  // 只在待机屏可见时轮询；对话澄清轮不占用额外请求。
  const progress = usePlanningProgress(
    planningProgressToken,
    phase === "generating",
  );
  useEffect(() => {
    if (initializedTrip.current || !requestedTripId || editingPlanId || draftItineraryData) return;
    initializedTrip.current = true;
    beginNewPlan(requestedTripId);
  }, [beginNewPlan, draftItineraryData, editingPlanId, requestedTripId]);

  useEffect(() => {
    if (!planningSeed || draftItineraryData) return;
    const task = window.setTimeout(clearPlanningSeed, 0);
    return () => window.clearTimeout(task);
  }, [clearPlanningSeed, draftItineraryData, planningSeed]);

  const savedSnapshot = editingPlanId && (draftItineraryData?.memory_context?.selected.length ?? 0) > 0
    ? draftItineraryData?.planning_snapshot : null;
  const savedSnapshotKey = editingPlanId && savedSnapshot
    ? `${editingPlanId}:${savedSnapshot.confirmation_token}` : null;
  const savedSnapshotConfirmed = Boolean(savedSnapshotKey && confirmedSavedSnapshotKey === savedSnapshotKey);
  const canCompare = Boolean(
    editingPlanId ? savedSnapshot && savedSnapshotConfirmed : brief && confirmationToken,
  );

  function confirmSavedSnapshot() {
    if (!savedSnapshotKey) return;
    setConfirmedSavedSnapshotKey(savedSnapshotKey);
  }

  async function handleConversationSend() {
    const text = prompt.trim();
    if (!text) {
      toastCode(1002);
      return;
    }
    const userMessage: PlanningConversationMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      planningModel: selectedModel,
    };
    const nextMessages = [...chatMessages, userMessage];
    setChatMessages(nextMessages);
    setPrompt("");
    setSaved(false);
    // Any new user requirement invalidates the checklist revision currently on
    // screen until the backend returns its newly normalized snapshot.
    setConfirmationToken(null);
    setSeedSource(null);
    const response = await planningTurn({
      message: text,
      planningModel: selectedModel,
      useMemory,
      context: null,
      messages: nextMessages.map(({ role, content, planningModel }) => ({
        role,
        content,
        planningModel,
      })),
      brief,
      confirmed: false,
    });
    if (!response) return;
    setBrief(response.brief);
    setChecklist(response.checklist);
    setConfirmationToken(response.confirmationToken);
    if (response.phase !== "completed") setConversationPhase(response.phase);
    if (response.assistantMessage) {
      setChatMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: response.assistantMessage,
          planningModel: response.planningModel,
        },
      ]);
    }
  }

  async function handleConfirmPlan() {
    if (
      !brief ||
      !confirmationToken ||
      conversationPhase !== "confirming" ||
      planning ||
      confirmationInFlight.current
    )
      return;
    confirmationInFlight.current = true;
    const confirmationText = "这份确认清单无误，请开始生成行程。";
    setGenerationRequested(true);
    try {
      // Confirmation is a state transition, not a magic chat phrase. Keep the
      // transcript unchanged and bind the request to the exact visible brief.
      const response = await planningTurn({
        message: confirmationText,
        planningModel: selectedModel,
        useMemory,
        context: null,
        messages: chatMessages.map(({ role, content, planningModel }) => ({
          role,
          content,
          planningModel,
        })),
        brief,
        confirmed: true,
        confirmationToken,
      });
      if (!response || response.itinerary) return;
      setBrief(response.brief);
      setChecklist(response.checklist);
      setConfirmationToken(response.confirmationToken);
      if (response.phase !== "completed") setConversationPhase(response.phase);
      if (response.assistantMessage) {
        setChatMessages((current) => [
          ...current,
          {
            id: `assistant-confirm-${Date.now()}`,
            role: "assistant",
            content: response.assistantMessage,
            planningModel: response.planningModel,
          },
        ]);
      }
    } finally {
      setGenerationRequested(false);
      confirmationInFlight.current = false;
    }
  }

  async function handleRefine() {
    const text = refinePrompt.trim();
    if (!text) {
      toast("请描述你想如何调整这份行程", "info");
      return;
    }
    comparisonEpoch.current += 1;
    setComparing(false);
    setSaved(false);
    setComparison(null);
    setComparisonBefore(null);
    setComparisonLabel("");
    setRefinePrompt("");
    const result = await planRefine(text, savedSnapshot?.planning_model ?? selectedModel);
    if (result) {
      // The original confirmation snapshot no longer describes this draft.
      // Comparing it against a fresh plan would attribute refinement changes
      // to memory removal, so hide comparison until a new intake is confirmed.
      setConfirmationToken(null);
      setConfirmedSavedSnapshotKey(null);
      toast("已按你的调整更新行程", "success");
    }
  }

  async function handleCompare(excludedMemoryId?: string) {
    const comparisonBrief = savedSnapshot?.brief ?? brief;
    const comparisonToken = savedSnapshot?.confirmation_token ?? confirmationToken;
    if (!draftItineraryData || !comparisonBrief || !comparisonToken || !canCompare || planning || comparing) return;
    const epoch = ++comparisonEpoch.current;
    const previous = draftItineraryData;
    const excluded = previous.memory_context?.selected.find((item) => item.id === excludedMemoryId);
    if (excludedMemoryId && !excluded) return;
    setComparing(true);
    try {
      const response = await planWithAI({
        message: "这份确认清单无误，请开始生成行程。",
        planningModel: savedSnapshot?.planning_model ?? selectedModel,
        context: null,
        messages: savedSnapshot ? [] : chatMessages.map(({ role, content, planningModel }) => ({ role, content, planningModel })),
        brief: comparisonBrief,
        confirmed: true,
        confirmationToken: comparisonToken,
        useMemory: Boolean(excludedMemoryId),
        excludedMemoryIds: excludedMemoryId ? [excludedMemoryId] : [],
      });
      if (comparisonEpoch.current !== epoch) return;
      if (response.itinerary) {
        setComparisonBefore(previous);
        setComparison(response.itinerary);
        setComparisonLabel(excluded ? `本次不参考「${excluded.text}」` : "本次不参考已保存的旅行记忆");
        toast("对照版已生成，原行程仍可保存和调整", "success");
      } else {
        toast(response.assistantMessage || "对照版尚未生成", "info");
      }
    } catch (error) {
      if (comparisonEpoch.current === epoch) toastError(error);
    } finally {
      if (comparisonEpoch.current === epoch) setComparing(false);
    }
  }

  async function handleSave() {
    const wasEditing = !!editingPlanId;
    const plan = await savePlan();
    if (plan) {
      setSaved(true);
      toast(wasEditing ? "行程已更新" : "行程已保存", "success");
    }
  }

  function handleStartOver() {
    comparisonEpoch.current += 1;
    setComparing(false);
    beginNewPlan(planningTripId ?? requestedTripId);
    setPrompt("");
    setRefinePrompt("");
    setSaved(false);
    setUseMemory(true);
    setComparison(null);
    setComparisonBefore(null);
    setComparisonLabel("");
    setChatMessages(INITIAL_MESSAGES);
    setBrief(null);
    setChecklist([]);
    setConversationPhase("collecting");
    setGenerationRequested(false);
    setConfirmationToken(null);
    setConfirmedSavedSnapshotKey(null);
  }

  function leavePlanning(action: () => void) {
    comparisonEpoch.current += 1;
    setComparing(false);
    beginNewPlan();
    setPrompt("");
    setRefinePrompt("");
    setSaved(false);
    setConfirmationToken(null);
    setConfirmedSavedSnapshotKey(null);
    action();
  }

  // 离开规划页前若有未保存草稿则拦截确认
  function guardedLeave(action: () => void) {
    if (hasUnsavedDraft && draftItineraryData) {
      pendingLeave.current = action;
      setShowLeaveConfirm(true);
    } else {
      action();
    }
  }

  function runPendingLeave() {
    const action = pendingLeave.current;
    pendingLeave.current = null;
    setShowLeaveConfirm(false);
    action?.();
  }

  useEffect(
    () =>
      registerBackHandler(() => {
        const leave = () => {
          beginNewPlan();
          setPrompt("");
          setRefinePrompt("");
          setSaved(false);
          goBackTo(backHref);
        };
        if (hasUnsavedDraft && draftItineraryData) {
          pendingLeave.current = leave;
          setShowLeaveConfirm(true);
          return;
        }
        leave();
      }),
    [
      beginNewPlan,
      draftItineraryData,
      backHref,
      goBackTo,
      hasUnsavedDraft,
      registerBackHandler,
    ],
  );

  return (
    <div className="app-page planning-page flex h-full min-h-0 flex-col">
      <TopBar
        title={editingPlanId ? "编辑行程" : "行程规划"}
        onBack={() => guardedLeave(() => leavePlanning(() => goBackTo(backHref)))}
        backLabel={requestedTripId ? "返回这次旅行" : editingPlanId ? "返回已保存行程" : "返回来源"}
        showUserBadge={false}
        showBack={Boolean(editingPlanId || requestedTripId || seedSource)}
        right={phase === "result" ? <div ref={setExportTarget} className="compact-export-slot" /> : undefined}
      />

      <div className="planning-context-strip">
        <button
          type="button"
          onClick={() => guardedLeave(() => leavePlanning(() => navigate({ page: "history" })))}
        >
          <History size={17} aria-hidden />历史行程
        </button>
        <Link href="/memory"><Brain size={17} aria-hidden />旅行记忆</Link>
      </div>

      {seedSource && phase === "conversation" ? (
        <div className="planning-seed-note" role="status">
          <span>已引用：{seedSource}</span>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {phase === "conversation" && (
          <><label className="planning-memory-choice">
            <input type="checkbox" checked={useMemory} onChange={(event) => setUseMemory(event.target.checked)} disabled={planning} />
            <span>本次允许参考已启用的旅行记忆</span>
          </label><PlanningConversation
            messages={chatMessages}
            phase={conversationPhase}
            checklist={checklist}
            value={prompt}
            busy={planning}
            confirmationReady={Boolean(confirmationToken)}
            onChange={setPrompt}
            onSend={() => void handleConversationSend()}
            onConfirm={() => void handleConfirmPlan()}
          /></>
        )}

        {phase === "generating" && (
          <div className="h-full overflow-y-auto px-4 py-6 no-scrollbar min-[400px]:px-5">
            <PlanningProgress snapshot={progress} />
          </div>
        )}

        {phase === "result" && draftItineraryData && (
          <div className="h-full overflow-y-auto pb-6 no-scrollbar">
            {savedSnapshot && !comparison ? (
              <SavedPlanningSnapshotReview
                brief={savedSnapshot.brief}
                model={savedSnapshot.planning_model}
                confirmed={savedSnapshotConfirmed}
                onConfirm={confirmSavedSnapshot}
              />
            ) : null}
            {comparison && comparisonBefore ? <PlanningVersionDiff before={comparisonBefore} after={comparison} conditionLabel={comparisonLabel} /> :
              draftItineraryData.memory_context?.selected.length && canCompare ? (
                <div className="planning-memory-compare">
                  <p>可以生成一版不参考历史记忆的方案作对照。两版差异也可能受模型和实时信息影响。</p>
                  <button type="button" onClick={() => void handleCompare()} disabled={planning || comparing}>{comparing ? "正在生成对照版…" : "不参考记忆，生成对照版"}</button>
                </div>
              ) : null}
            <ItineraryDetail
              data={draftItineraryData}
              exportTarget={exportTarget}
              onExcludeMemory={canCompare ? (id) => void handleCompare(id) : undefined}
              comparingMemory={comparing}
            />
          </div>
        )}
      </div>

      {/* 结果态底部操作区：调整与保存 */}
      {phase === "result" && draftItineraryData && (
        <div className="planning-result-composer">
          <div className="flex items-end gap-2">
            <textarea
              value={refinePrompt}
              onChange={(e) => setRefinePrompt(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  void handleRefine();
                }
              }}
              placeholder="想怎样调整行程？"
              rows={1}
              className="max-h-24 min-h-[2.75rem] flex-1 resize-none rounded-2xl border border-border/80 bg-card px-3.5 py-3 text-sm leading-snug text-foreground outline-none transition placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
            <button
              type="button"
              onClick={() => void handleRefine()}
              className="ui-icon-button flex size-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-md"
              aria-label="发送调整"
            >
              <Send className="h-5 w-5" />
            </button>
          </div>

          <div className="mt-2.5">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || (saved && !hasUnsavedDraft)}
              className="ui-pressable flex min-h-12 w-full items-center justify-center gap-1.5 rounded-full bg-primary py-2.5 text-sm font-semibold text-primary-foreground shadow-md disabled:opacity-60"
            >
              <Save className="h-4 w-4" />
              {saving
                ? "保存中…"
                : saved && !hasUnsavedDraft
                  ? "已保存"
                  : editingPlanId
                    ? "更新行程"
                    : "保存行程"}
            </button>
          </div>

          <div className="mt-2 flex items-center justify-center gap-4">
            <button
              type="button"
              onClick={handleStartOver}
              className="ui-pressable flex min-h-11 items-center gap-1 rounded-full px-3 text-xs font-medium text-muted-foreground"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              重新开始
            </button>
            {saved && (
              <button
                type="button"
                onClick={() =>
                  guardedLeave(() =>
                    leavePlanning(() => navigate({ page: "history" })),
                  )
                }
                className="ui-pressable min-h-11 rounded-full px-3 text-xs font-medium text-primary"
              >
                查看已保存行程 →
              </button>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={showLeaveConfirm}
        title="还有未保存的行程"
        description="要先保存再离开吗？"
        onClose={() => {
          pendingLeave.current = null;
          setShowLeaveConfirm(false);
        }}
        actions={[
          {
            label: saving ? "保存中…" : "保存行程",
            variant: "primary",
            onClick: () => {
              void (async () => {
                const plan = await savePlan();
                if (plan) runPendingLeave();
              })();
            },
          },
          {
            label: "不保存，直接离开",
            variant: "danger",
            onClick: () => {
              discardDraft();
              runPendingLeave();
            },
          },
          {
            label: "取消",
            variant: "ghost",
            onClick: () => {
              pendingLeave.current = null;
              setShowLeaveConfirm(false);
            },
          },
        ]}
      />
      <BottomNav />
    </div>
  );
}

function SavedPlanningSnapshotReview({
  brief,
  model,
  confirmed,
  onConfirm,
}: {
  brief: PlanningBrief;
  model: PlanningModel;
  confirmed: boolean;
  onConfirm: () => void;
}) {
  const rows: [string, string][] = [
    ["出发地", brief.origin || "未记录"],
    ["目的地", brief.destinations.join("、") || "未记录"],
    ["日期", `${brief.startDate || "未记录"} 至 ${brief.endDate || "未记录"}`],
    ["同行人数", brief.travelerCount ? `${brief.travelerCount} 人` : "未指定"],
    ["预算", brief.budget || "未指定"],
    ["大交通", brief.transportPreference || "未指定"],
    ["住宿", brief.lodgingPreference || "未指定"],
    ["兴趣", brief.interests.join("、") || "未指定"],
    ["约束", brief.constraints.join("；") || "无"],
    ["假设", brief.assumptions.join("；") || "无"],
    ["需求概述", brief.summary || "无"],
    ["详细需求", brief.detailRequirements || "无"],
  ];
  return <section className="planning-memory-compare" aria-label="保存时的需求记录">
    <h2>保存时的需求记录</h2>
    <p>重新规划前，请核对以下记录。它由保存的行程携带，不能证明行程变化由某条记忆造成。</p>
    <dl className="planning-snapshot-details">
      {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      <div><dt>原规划模型</dt><dd>{model}</dd></div>
    </dl>
    {confirmed ? <p role="status">已核对；现在可以生成完整对照版。原行程会保留。</p> :
      <button type="button" onClick={onConfirm}>我已核对，允许按这份需求重新规划</button>}
  </section>;
}

function PlanningVersionDiff({ before, after, conditionLabel }: { before: ItineraryData; after: ItineraryData; conditionLabel: string }) {
  const changes = after.itinerary.flatMap((day, index) => {
    const prior = before.itinerary.find((item) => item.date === day.date) ?? before.itinerary[index];
    const lines = (items: typeof day.schedules) => items.map((item) => [
      [item.start_time, item.end_time].filter(Boolean).join("–") || item.time_period,
      item.place_name,
      item.activity,
      item.transport,
    ].filter(Boolean).join(" · "));
    const oldNames = prior ? lines(prior.schedules) : [];
    const newNames = lines(day.schedules);
    return JSON.stringify(oldNames) === JSON.stringify(newNames)
      ? []
      : [{ date: day.date, before: oldNames, after: newNames }];
  });
  return <section className="planning-version-diff" aria-label="两版行程对照">
    <h2>两版行程对照</h2>
    <p>原方案与“{conditionLabel}”的重新规划方案对照。实时信息与后来修改的旅行记忆也可能让安排发生变化。</p>
    {changes.length ? <>
      <strong>{changes.length} 天的安排有变化</strong>
      {changes.map((item) => <div className="planning-version-day" key={item.date}>
        <span>{item.date}</span>
        <p>原方案：{item.before.join("、") || "无具体地点"}</p>
        <p>{conditionLabel}：{item.after.join("、") || "无具体地点"}</p>
      </div>)}
    </> : <strong>两版每日的时间、地点、活动和交通描述相同；预订等其他内容仍需分别核对</strong>}
  </section>;
}
