"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { ArrowRight, CalendarDays, Camera, FileText, Map, Plus, Route, X } from "lucide-react"
import { BottomNav } from "@/components/shared/bottom-nav"
import { useApp } from "@/components/shared/app-context"
import { handleImageError, resolveAssetUrl } from "@/lib/asset"

export function HomeView() {
  const { trips, loadError, reloadAll } = useApp()
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    if (!creating) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setCreating(false)
    }
    document.addEventListener("keydown", closeOnEscape)
    return () => document.removeEventListener("keydown", closeOnEscape)
  }, [creating])

  return (
    <div className="app-page trips-page">
      <header className="collection-header">
        <div className="brand-mark" aria-label="旅有所图">旅有所图</div>
        <div className="collection-title-row">
          <h1>我的旅行</h1>
          <button type="button" className="primary-quiet-button" onClick={() => setCreating(true)}>
            <Plus size={17} aria-hidden />新建旅行
          </button>
        </div>
      </header>

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
                    <img src={resolveAssetUrl(trip.coverImage)} alt="" onError={handleImageError} />
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
          <section className="plain-state empty-trip-state">
            <Map size={28} aria-hidden />
            <p>还没有旅行</p>
            <button type="button" onClick={() => setCreating(true)}>新建旅行</button>
          </section>
        )}
      </main>

      {creating ? (
        <div className="action-sheet-backdrop" onClick={() => setCreating(false)}>
          <section className="action-sheet" role="dialog" aria-modal="true" aria-label="新建旅行" onClick={(event) => event.stopPropagation()}>
            <div className="action-sheet-title">
              <h2>新建旅行</h2>
              <button type="button" onClick={() => setCreating(false)} aria-label="关闭"><X size={18} /></button>
            </div>
            <Link href="/create"><Camera size={20} /><span>用照片创建</span><ArrowRight size={17} /></Link>
            <Link href="/planning"><Route size={20} /><span>规划新旅行</span><ArrowRight size={17} /></Link>
          </section>
        </div>
      ) : null}

      <BottomNav />
    </div>
  )
}
