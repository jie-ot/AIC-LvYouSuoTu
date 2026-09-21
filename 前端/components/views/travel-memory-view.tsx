"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import {
  Camera,
  Check,
  ChevronDown,
  ChevronRight,
  Layers3,
  MapPinned,
  Pencil,
  Plus,
  Route,
  Trash2,
  X,
} from "lucide-react"
import { BottomNav } from "@/components/shared/bottom-nav"
import { useApp } from "@/components/shared/app-context"
import { ConfirmDialog } from "@/components/shared/confirm-dialog"
import {
  confirmTravelMemoryPattern,
  createTravelMemoryItem,
  deleteTravelMemoryItem,
  getTravelMemory,
  patchTravelMemoryItem,
  updateTravelMemorySettings,
} from "@/lib/api"
import { handleImageError, resolveAssetUrl } from "@/lib/asset"
import type {
  TravelMemoryDescription,
  TravelMemoryDisplay,
  TravelMemoryPattern,
} from "@/types"

const CATEGORIES = [
  ["transport", "交通"],
  ["hotel", "住宿"],
  ["pace", "行程节奏"],
  ["food", "餐饮"],
  ["budget", "预算"],
  ["accessibility", "同行与无障碍"],
  ["attractions", "想去的地方"],
  ["other", "其他"],
] as const

const PATTERN_ICONS = { photos: Camera, plans: Route, combined: Layers3 } as const

export function TravelMemoryView() {
  const { toast, toastError } = useApp()
  const [memory, setMemory] = useState<TravelMemoryDisplay | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [showAllTrips, setShowAllTrips] = useState(false)
  const [text, setText] = useState("")
  const [category, setCategory] = useState("hotel")
  const [editing, setEditing] = useState<TravelMemoryDescription | null>(null)
  const [pendingDelete, setPendingDelete] = useState<TravelMemoryDescription | null>(null)
  const [editText, setEditText] = useState("")
  const [editCategory, setEditCategory] = useState("other")

  const saved = useMemo(
    () => memory?.memories.filter((item) => item.state !== "candidate") ?? [],
    [memory],
  )
  const suggested = useMemo(
    () => memory?.memories.filter((item) => item.state === "candidate") ?? [],
    [memory],
  )
  const patterns = useMemo(
    () => memory?.patterns.filter((item) => !item.confirmed) ?? [],
    [memory],
  )
  const footprints = memory?.footprints ?? []
  const visibleFootprints = showAllTrips ? footprints : footprints.slice(0, 4)

  useEffect(() => {
    let active = true
    void getTravelMemory()
      .then((value) => { if (active) setMemory(value) })
      .catch((error) => { if (active) toastError(error) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [toastError])

  async function update(key: string, action: () => Promise<TravelMemoryDisplay>, message?: string) {
    if (!memory || busy) return
    setBusy(key)
    try {
      setMemory(await action())
      if (message) toast(message, "success")
    } catch (error) {
      toastError(error)
    } finally {
      setBusy(null)
    }
  }

  function startEdit(item: TravelMemoryDescription) {
    setEditing(item)
    setEditText(item.content)
    setEditCategory(item.category ?? "other")
  }

  return (
    <div className="app-page memory-page">
      <header className="memory-header">
        <div className="collection-title-row">
          <h1>旅行记忆</h1>
          <button type="button" className="primary-quiet-button" onClick={() => setAdding(true)}>
            <Plus size={18} aria-hidden />添加要求
          </button>
        </div>
      </header>

      <main className="memory-main">
        {loading ? <div className="plain-state"><p>正在读取…</p></div> : null}
        {!loading && memory ? (
          <>
            <section className="memory-stats" aria-label="旅行记忆概览">
              <MemoryStat value={memory.stats.tripCount} label="次旅行" />
              <MemoryStat value={memory.stats.placeCount} label="个地方" />
              <MemoryStat value={memory.stats.photoCount} label="张照片" />
              <MemoryStat value={memory.stats.planCount} label="份规划" />
            </section>

            {footprints.length ? (
              <section className="memory-section memory-footprint-section">
                <div className="memory-section-title"><h2>旅行足迹</h2><span>{footprints.length}</span></div>
                <div className="memory-footprint-grid">
                  {visibleFootprints.map((item) => (
                    <Link
                      key={item.id}
                      href={`/trips/detail?tripId=${encodeURIComponent(item.tripId)}&from=memory`}
                      className="memory-footprint-card"
                    >
                      {item.coverImage ? (
                        <img src={resolveAssetUrl(item.coverImage)} alt="" onError={handleImageError} />
                      ) : (
                        <div className="memory-footprint-placeholder"><MapPinned size={22} aria-hidden /></div>
                      )}
                      <div className="memory-footprint-copy">
                        <div className="memory-footprint-heading"><strong>{item.title}</strong><span>{item.stateLabel}</span></div>
                        <p>{item.dateLabel || "日期待补"}</p>
                        {item.travelTypes.length ? (
                          <div className="memory-tags">{item.travelTypes.map((tag) => <span key={tag}>{tag}</span>)}</div>
                        ) : null}
                        {item.highlights.length ? <p className="memory-highlights">{item.highlights.slice(0, 3).join(" · ")}</p> : null}
                        {item.paceLabel ? <p className="memory-pace">{item.paceLabel}</p> : null}
                        <div className="memory-source-line">{item.sourceLabels.join(" · ")}<ChevronRight size={16} aria-hidden /></div>
                      </div>
                    </Link>
                  ))}
                </div>
                {footprints.length > 4 ? (
                  <button type="button" className="memory-show-all" onClick={() => setShowAllTrips((value) => !value)}>
                    {showAllTrips ? "收起" : `查看全部 ${footprints.length} 次旅行`}
                    <ChevronDown className={showAllTrips ? "is-open" : ""} size={17} aria-hidden />
                  </button>
                ) : null}
              </section>
            ) : null}

            {patterns.length ? (
              <section className="memory-section">
                <div className="memory-section-title"><h2>正在形成</h2><span>{patterns.length}</span></div>
                <div className="memory-pattern-list">
                  {patterns.map((item) => (
                    <PatternRow
                      key={item.id}
                      item={item}
                      busy={busy === item.id}
                      onConfirm={() => update(
                        item.id,
                        () => confirmTravelMemoryPattern(item.id, memory.version),
                        "已用于后续规划",
                      )}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            {suggested.length ? (
              <section className="memory-section">
                <div className="memory-section-title"><h2>待你确认</h2><span>{suggested.length}</span></div>
                <div className="memory-list">
                  {suggested.map((item) => (
                    <MemoryRow
                      key={item.id}
                      item={item}
                      busy={busy === item.id}
                      actionLabel="保存"
                      onAction={() => update(
                        item.id,
                        () => patchTravelMemoryItem(item.id, { confirm: true, expectedVersion: memory.version }),
                        "已保存",
                      )}
                      onEdit={() => startEdit(item)}
                      onDelete={() => setPendingDelete(item)}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            <section className="memory-section">
              <div className="memory-section-title"><h2>你的要求</h2><span>{saved.length}</span></div>
              {saved.length ? (
                <div className="memory-list">
                  {saved.map((item) => (
                    <MemoryRow
                      key={item.id}
                      item={item}
                      busy={busy === item.id}
                      onToggle={() => update(
                        item.id,
                        () => patchTravelMemoryItem(item.id, {
                          enabled: item.enabled === false,
                          expectedVersion: memory.version,
                        }),
                      )}
                      onEdit={() => startEdit(item)}
                      onDelete={() => setPendingDelete(item)}
                    />
                  ))}
                </div>
              ) : (
                <button type="button" className="memory-empty" onClick={() => setAdding(true)}>
                  添加交通、住宿或饮食要求<ChevronRight size={18} />
                </button>
              )}
            </section>

            <section className="memory-setting-row">
              <span><strong>规划时使用已保存要求</strong></span>
              <button
                type="button"
                className={`switch-control ${memory.enabled === false ? "" : "is-on"}`}
                role="switch"
                aria-checked={memory.enabled !== false}
                aria-label="规划时使用已保存要求"
                disabled={busy !== null}
                onClick={() => update(
                  "settings",
                  () => updateTravelMemorySettings({ enabled: memory.enabled === false, expectedVersion: memory.version }),
                )}
              ><span /></button>
            </section>
          </>
        ) : null}
      </main>

      {adding ? (
        <MemoryEditor
          title="添加旅行要求"
          text={text}
          category={category}
          busy={busy === "create"}
          onText={setText}
          onCategory={setCategory}
          onClose={() => { setAdding(false); setText("") }}
          onSave={() => {
            const value = text.trim()
            if (!value || !memory) return
            void update(
              "create",
              () => createTravelMemoryItem({ text: value, category, expectedVersion: memory.version }),
              "已添加",
            ).then(() => { setAdding(false); setText("") })
          }}
        />
      ) : null}

      {editing && memory ? (
        <MemoryEditor
          title="编辑旅行要求"
          text={editText}
          category={editCategory}
          busy={busy === editing.id}
          onText={setEditText}
          onCategory={setEditCategory}
          onClose={() => setEditing(null)}
          onSave={() => {
            const value = editText.trim()
            if (!value) return
            void update(
              editing.id,
              () => patchTravelMemoryItem(editing.id, {
                text: value,
                category: editCategory,
                expectedVersion: memory.version,
              }),
              "已更新",
            ).then(() => setEditing(null))
          }}
        />
      ) : null}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="删除这条旅行要求？"
        description={pendingDelete?.content ?? ""}
        onClose={() => setPendingDelete(null)}
        actions={[
          {
            label: busy === pendingDelete?.id ? "删除中…" : "删除",
            variant: "danger",
            onClick: () => {
              if (!pendingDelete || !memory) return
              const item = pendingDelete
              void update(
                item.id,
                () => deleteTravelMemoryItem(item.id, memory.version),
                "已删除",
              ).then(() => setPendingDelete(null))
            },
          },
          { label: "取消", variant: "ghost", onClick: () => setPendingDelete(null) },
        ]}
      />

      <BottomNav />
    </div>
  )
}

function MemoryStat({ value, label }: { value: number; label: string }) {
  return <div><strong>{value}</strong><span>{label}</span></div>
}

function PatternRow({ item, busy, onConfirm }: {
  item: TravelMemoryPattern
  busy: boolean
  onConfirm: () => void
}) {
  const Icon = PATTERN_ICONS[item.sourceKind]
  return (
    <article className="memory-pattern-row">
      <span className="memory-pattern-icon"><Icon size={19} aria-hidden /></span>
      <div>
        <strong>{item.title}</strong>
        <p>{item.content}</p>
        <div className="memory-pattern-sources">{item.sourceLabels.map((label) => <span key={label}>{label}</span>)}</div>
      </div>
      {item.confirmable ? (
        <button type="button" onClick={onConfirm} disabled={busy}>{busy ? "保存中…" : "用于规划"}</button>
      ) : null}
    </article>
  )
}

function MemoryRow({ item, busy, actionLabel, onAction, onToggle, onEdit, onDelete }: {
  item: TravelMemoryDescription
  busy: boolean
  actionLabel?: string
  onAction?: () => void
  onToggle?: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <article className={`memory-row ${item.enabled === false ? "is-muted" : ""}`}>
      <div className="memory-row-copy">
        <div className="memory-row-meta">
          <span>{item.title}</span>
          {item.sourceTripId ? (
            <Link href={`/trips/detail?tripId=${encodeURIComponent(item.sourceTripId)}&from=memory`}>{item.sourceLabel ?? "旅行中填写"}</Link>
          ) : <span>{item.sourceLabel ?? "手动添加"}</span>}
        </div>
        <p>{item.content}</p>
      </div>
      <div className="memory-row-actions">
        {onAction ? <button type="button" onClick={onAction} disabled={busy}><Check size={17} />{actionLabel}</button> : null}
        {onToggle ? (
          <button type="button" onClick={onToggle} disabled={busy} aria-label={item.enabled === false ? "启用" : "停用"}>
            {item.enabled === false ? "启用" : "停用"}
          </button>
        ) : null}
        <button type="button" onClick={onEdit} disabled={busy} aria-label="编辑"><Pencil size={17} /></button>
        <button type="button" onClick={onDelete} disabled={busy} aria-label="删除"><Trash2 size={17} /></button>
      </div>
    </article>
  )
}

function MemoryEditor({ title, text, category, busy, onText, onCategory, onClose, onSave }: {
  title: string
  text: string
  category: string
  busy: boolean
  onText: (value: string) => void
  onCategory: (value: string) => void
  onClose: () => void
  onSave: () => void
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose()
    }
    document.addEventListener("keydown", closeOnEscape)
    return () => document.removeEventListener("keydown", closeOnEscape)
  }, [busy, onClose])

  return (
    <div className="action-sheet-backdrop" onClick={onClose}>
      <section className="action-sheet memory-editor" role="dialog" aria-modal="true" aria-label={title} onClick={(event) => event.stopPropagation()}>
        <div className="action-sheet-title"><h2>{title}</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></div>
        <label><span>类型</span><select value={category} onChange={(event) => onCategory(event.target.value)}>{CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label><span>要求</span><textarea value={text} onChange={(event) => onText(event.target.value)} placeholder="例如：酒店要安静，步行 10 分钟内到地铁" rows={4} autoFocus /></label>
        <button type="button" className="memory-save-button" onClick={onSave} disabled={busy || text.trim().length < 2}>{busy ? "保存中…" : "保存"}</button>
      </section>
    </div>
  )
}
