"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { ArrowRight, Camera, FileText, Pencil, Plus, Route, Trash2, X } from "lucide-react"
import { BottomNav } from "@/components/shared/bottom-nav"
import { ConfirmDialog } from "@/components/shared/confirm-dialog"
import { TopBar } from "@/components/shared/top-bar"
import { useApp } from "@/components/shared/app-context"
import { handleImageError, resolveAssetUrl } from "@/lib/asset"
import { deleteTrip, updateTrip } from "@/lib/api"

export function TripDetailView() {
  const search = useSearchParams()
  const tripId = search.get("tripId") ?? ""
  const sourceId = search.get("sourceId") ?? ""
  const tripBackHref = search.get("from") === "memory"
    ? "/memory"
    : search.get("from") === "report" && sourceId
      ? `/reports/detail?reportId=${encodeURIComponent(sourceId)}`
      : search.get("from") === "postcard" && sourceId
        ? `/postcards/detail?groupId=${encodeURIComponent(sourceId)}`
        : search.get("from") === "history" && sourceId
          ? `/planning/history/detail?planId=${encodeURIComponent(sourceId)}`
          : "/"
  const tripBackLabel = search.get("from") === "memory"
    ? "返回旅行记忆"
    : search.get("from") === "report"
      ? "返回旅行报告"
      : search.get("from") === "postcard"
        ? "返回明信片"
        : search.get("from") === "history"
          ? "返回行程"
          : "返回我的旅行"
  const { trips, plans, postcardGroups, reports, beginNewPlan, navigate, upsertTrip, removeTrip: removeTripFromState, toast, toastError } = useApp()
  const trip = trips.find((item) => item.id === tripId)
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState("")
  const [savingTitle, setSavingTitle] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deletingTrip, setDeletingTrip] = useState(false)
  const tripPlans = plans.filter((item) => item.tripId === tripId)
  const tripPostcards = postcardGroups.filter((item) => item.tripId === tripId)
  const tripReports = reports.filter((item) => item.tripId === tripId)

  useEffect(() => {
    if (!renaming) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !savingTitle) setRenaming(false)
    }
    document.addEventListener("keydown", closeOnEscape)
    return () => document.removeEventListener("keydown", closeOnEscape)
  }, [renaming, savingTitle])

  async function saveTitle() {
    if (!trip || savingTitle || title.trim().length < 2) return
    setSavingTitle(true)
    try {
      upsertTrip(await updateTrip(trip.id, { title: title.trim() }))
      setRenaming(false)
      toast("旅行名称已更新", "success")
    } catch (error) {
      toastError(error)
    } finally {
      setSavingTitle(false)
    }
  }

  async function removeTrip() {
    if (!trip || deletingTrip) return
    setDeletingTrip(true)
    try {
      await deleteTrip(trip.id)
      removeTripFromState(trip.id)
      toast("旅行已删除", "success")
      navigate({ page: "home" })
    } catch (error) {
      toastError(error)
    } finally {
      setDeletingTrip(false)
      setConfirmDelete(false)
    }
  }

  if (!trip) {
    return (
      <div className="app-page detail-page">
        <TopBar title="旅行不存在" showUserBadge={false} backHref={tripBackHref} backLabel={tripBackLabel} />
        <section className="plain-state"><Link href="/">返回旅行</Link></section>
        <BottomNav />
      </div>
    )
  }

  return (
    <div className="app-page detail-page trip-detail-page">
      <TopBar
        title={trip.title}
        subtitle={trip.dateLabel}
        showUserBadge={false}
        backHref={tripBackHref}
        backLabel={tripBackLabel}
        right={<div className="trip-title-actions">
          <button type="button" onClick={() => {
            setTitle(trip.title)
            setRenaming(true)
          }}><Pencil size={15} aria-hidden />改名</button>
          {!tripPlans.length && !tripPostcards.length && !tripReports.length ? <button type="button" className="trip-title-delete" aria-label="删除旅行" onClick={() => setConfirmDelete(true)}><Trash2 size={15} aria-hidden /></button> : null}
        </div>}
      />
      <main className="trip-detail-main">
        <div className="trip-primary-actions">
          <Link href={`/create?tripId=${encodeURIComponent(trip.id)}`}><Camera size={18} />用照片创作</Link>
          <Link
            href={`/planning?tripId=${encodeURIComponent(trip.id)}`}
            onClick={() => beginNewPlan(trip.id)}
          ><Route size={18} />规划行程</Link>
        </div>

        <section className="trip-section">
          <header><h2>行程</h2><Link href={`/planning?tripId=${encodeURIComponent(trip.id)}`} onClick={() => beginNewPlan(trip.id)}><Plus size={16} />添加</Link></header>
          {tripPlans.length ? tripPlans.map((plan) => (
            <button key={plan.id} type="button" className="trip-content-row" onClick={() => navigate({ page: "history-detail", planId: plan.id, tripId: trip.id, from: "trip" })}>
              <span className="trip-row-icon"><Route size={18} /></span>
              <span><strong>{plan.location}</strong><small>{plan.dateLabel}</small></span>
              <ArrowRight size={17} />
            </button>
          )) : <p className="trip-section-empty">尚未添加</p>}
        </section>

        <section className="trip-section">
          <header><h2>明信片</h2><Link href={`/create?tripId=${encodeURIComponent(trip.id)}&mode=postcard`}><Plus size={16} />制作</Link></header>
          {tripPostcards.length ? tripPostcards.map((group) => (
            <Link key={group.id} href={`/postcards/detail?groupId=${encodeURIComponent(group.id)}&from=trip&tripId=${encodeURIComponent(trip.id)}`} className="trip-artifact-row">
              <img src={resolveAssetUrl(group.coverImage)} alt="" onError={handleImageError} />
              <span><strong>{group.postcards.length} 张明信片</strong><small>{group.dateLabel}</small></span>
              <ArrowRight size={17} />
            </Link>
          )) : <p className="trip-section-empty">尚未制作</p>}
        </section>

        <section className="trip-section">
          <header><h2>旅行报告</h2><Link href={`/create?tripId=${encodeURIComponent(trip.id)}&mode=report`}><Plus size={16} />生成</Link></header>
          {tripReports.length ? tripReports.map((report) => (
            <Link key={report.id} href={`/reports/detail?reportId=${encodeURIComponent(report.id)}&from=trip&tripId=${encodeURIComponent(trip.id)}`} className="trip-content-row">
              <span className="trip-row-icon"><FileText size={18} /></span>
              <span><strong>旅行报告</strong><small>{report.dateLabel}</small></span>
              <ArrowRight size={17} />
            </Link>
          )) : <p className="trip-section-empty">尚未生成</p>}
        </section>
      </main>
      {renaming ? <div className="action-sheet-backdrop" onClick={() => !savingTitle && setRenaming(false)}>
        <section className="action-sheet memory-editor" role="dialog" aria-modal="true" aria-label="修改旅行名称" onClick={(event) => event.stopPropagation()}>
          <div className="action-sheet-title"><h2>修改旅行名称</h2><button type="button" onClick={() => setRenaming(false)} aria-label="关闭"><X size={18} /></button></div>
          <label><span>名称</span><input value={title} maxLength={40} autoFocus onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => {
            if (event.key === "Enter") void saveTitle()
          }} /></label>
          <button type="button" className="memory-save-button" disabled={savingTitle || title.trim().length < 2} onClick={() => void saveTitle()}>{savingTitle ? "保存中…" : "保存"}</button>
        </section>
      </div> : null}
      <ConfirmDialog
        open={confirmDelete}
        title="删除这次旅行？"
        description="这次旅行尚无内容，删除后无法恢复。"
        onClose={() => !deletingTrip && setConfirmDelete(false)}
        actions={[
          { label: deletingTrip ? "删除中…" : "删除", variant: "danger", onClick: () => void removeTrip() },
          { label: "取消", variant: "ghost", onClick: () => setConfirmDelete(false) },
        ]}
      />
      <BottomNav />
    </div>
  )
}
