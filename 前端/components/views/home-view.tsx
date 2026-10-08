"use client"

import { useState } from "react"
import Link from "next/link"
import { ArrowRight, CalendarDays, Camera, FileText, Map, Plus, Route, X } from "lucide-react"
import { BottomNav } from "@/components/shared/bottom-nav"
import { useApp } from "@/components/shared/app-context"
import { Modal } from "@/components/shared/modal"
import { CollectionHeader } from "@/components/shared/collection-header"
import { EmptyState } from "@/components/shared/empty-state"
import { handleImageError, resolveAssetUrl } from "@/lib/asset"

export function HomeView() {
  const { trips, loadError, reloadAll } = useApp()
  const [creating, setCreating] = useState(false)

  return (
    <div className="app-page trips-page">
      <CollectionHeader
        section="旅行"
        title="我的旅行"
        description="把走过的路，收进自己的旅行集。"
        count={trips.length ? `${trips.length} 次旅行` : undefined}
        action={<button type="button" className="primary-quiet-button" onClick={() => setCreating(true)}>
          <Plus size={17} aria-hidden />新建旅行
        </button>}
      />

      <main className="collection-main">
        {loadError.trips ? (
          <section className="plain-state">
            <p>旅行加载失败</p>
            <button type="button" onClick={reloadAll}>重试</button>
          </section>
        ) : trips.length ? (
          <div className="trip-grid">
            {trips.map((trip) => (
              <Link key={trip.id} href={`/trips/detail?tripId=${encodeURIComponent(trip.id)}`} className={`trip-card ${trip.coverImage ? "has-cover" : "no-cover"}`}>
                <div className="trip-cover">
                  {trip.coverImage ? (
                    <img src={resolveAssetUrl(trip.coverImage)} alt="" loading="lazy" decoding="async" onError={handleImageError} />
                  ) : (
                    <div className="trip-cover-empty"><Map size={30} aria-hidden /></div>
                  )}
                  <span className="trip-open"><ArrowRight size={17} aria-hidden /></span>
                </div>
                <div className="trip-card-body">
                  <h2>{trip.title}</h2>
                  {trip.dateLabel && trip.dateLabel !== "日期待定"
                    ? <p><CalendarDays size={14} aria-hidden />{trip.dateLabel}</p>
                    : null}
                  <div className="trip-counts" aria-label="旅行内容">
                    <span><Route size={14} aria-hidden />行程 {trip.planCount}</span>
                    <span><Camera size={14} aria-hidden />明信片 {trip.postcardCount}</span>
                    <span><FileText size={14} aria-hidden />报告 {trip.reportCount}</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<Map size={28} aria-hidden />}
            title="从一段旅行开始"
            description="用照片留住回忆，或为下一次出发做个计划。"
          >
            <Link href="/create" className="primary-action"><Camera size={17} aria-hidden />用照片创建</Link>
            <Link href="/planning" className="secondary-action"><Route size={17} aria-hidden />规划新旅行</Link>
          </EmptyState>
        )}
      </main>

      <Modal open={creating} onClose={() => setCreating(false)} className="action-modal" label="新建旅行">
          <section className="action-sheet">
            <div className="action-sheet-title">
              <h2>新建旅行</h2>
              <button type="button" onClick={() => setCreating(false)} aria-label="关闭"><X size={18} /></button>
            </div>
            <Link href="/create"><Camera size={20} /><span>用照片创建</span><ArrowRight size={17} /></Link>
            <Link href="/planning"><Route size={20} /><span>规划新旅行</span><ArrowRight size={17} /></Link>
          </section>
      </Modal>

      <BottomNav />
    </div>
  )
}
