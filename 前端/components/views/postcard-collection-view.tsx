"use client"

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { ChevronLeft, Download, MapPin } from "lucide-react"
import { useApp } from "@/components/shared/app-context"
import { ConfirmDialog } from "@/components/shared/confirm-dialog"
import { EmptyState } from "@/components/shared/empty-state"
import { PLACEHOLDER_IMAGE, handleImageError, resolveAssetUrl } from "@/lib/asset"
import { displayPlace } from "@/lib/place"
import { savePostcardImage } from "@/lib/postcard-save"
import type { Postcard } from "@/types"

const LONG_PRESS_MS = 650
const LONG_PRESS_MOVE_TOLERANCE = 12

export function PostcardCollectionView() {
  const searchParams = useSearchParams()
  const { postcardGroups, trips, goBackTo, toast } = useApp()
  const group = postcardGroups.find((g) => g.id === searchParams.get("groupId"))
  const place = group
    ? displayPlace(group.location, trips.find((trip) => trip.id === group.tripId)?.title)
    : ""
  const returnTripId = searchParams.get("tripId") ?? group?.tripId
  const backHref = searchParams.get("from") === "trip" && returnTripId
    ? `/trips/detail?tripId=${encodeURIComponent(returnTripId)}`
    : "/postcards"
  const initialIndex = Math.max(0, Math.min((group?.postcards.length ?? 1) - 1, Number(searchParams.get("index")) || 0))
  const [active, setActive] = useState(initialIndex)
  const [pendingSave, setPendingSave] = useState<Postcard | null>(null)
  const [saving, setSaving] = useState(false)
  const trackRef = useRef<HTMLDivElement>(null)
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pressStartRef = useRef<{ x: number; y: number } | null>(null)

  const cancelLongPress = () => {
    if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current)
    longPressTimerRef.current = null
    pressStartRef.current = null
  }

  useEffect(
    () => () => {
      if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current)
    },
    [],
  )

  useEffect(() => {
    const track = trackRef.current
    if (track) track.scrollTo({ left: initialIndex * track.clientWidth, behavior: "instant" })
  }, [group?.id, initialIndex])

  const startLongPress = (event: ReactPointerEvent<HTMLImageElement>, postcard: Postcard) => {
    if (event.pointerType === "mouse" && event.button !== 0) return
    cancelLongPress()
    pressStartRef.current = { x: event.clientX, y: event.clientY }
    longPressTimerRef.current = setTimeout(() => {
      longPressTimerRef.current = null
      pressStartRef.current = null
      if ("vibrate" in navigator) navigator.vibrate(30)
      setPendingSave(postcard)
    }, LONG_PRESS_MS)
  }

  const moveLongPress = (event: ReactPointerEvent<HTMLImageElement>) => {
    const start = pressStartRef.current
    if (!start) return
    if (
      Math.abs(event.clientX - start.x) > LONG_PRESS_MOVE_TOLERANCE ||
      Math.abs(event.clientY - start.y) > LONG_PRESS_MOVE_TOLERANCE
    ) {
      cancelLongPress()
    }
  }

  if (!group) {
    return (
      <div className="flex flex-1 flex-col">
        <EmptyState
          icon={<MapPin className="size-7" aria-hidden />}
          title="内容已被删除"
          description="该明信片组不存在或已被移除。"
        >
          <button
            type="button"
            onClick={() => goBackTo(backHref)}
            className="ui-pressable min-h-12 rounded-full bg-primary px-6 py-2.5 text-sm font-semibold text-primary-foreground shadow-md"
          >
            返回
          </button>
        </EmptyState>
      </div>
    )
  }

  const onScroll = () => {
    const el = trackRef.current
    if (!el) return
    const idx = Math.round(el.scrollLeft / el.clientWidth)
    if (idx !== active) setActive(idx)
  }

  const current = group.postcards[active]

  return (
    <div className="postcard-viewer">
      {/* 顶部栏 */}
      <header className="viewer-header">
        <button
          type="button"
          onClick={() => goBackTo(backHref)}
          className="icon-button"
          aria-label={returnTripId && searchParams.get("from") === "trip" ? "返回这次旅行" : "返回明信片"}
        >
          <ChevronLeft className="size-5" aria-hidden />
        </button>
        <div className="viewer-counter">
          {active + 1} / {group.postcards.length}
        </div>
        {group.tripId ? <Link className="viewer-trip-link" href={`/trips/detail?tripId=${encodeURIComponent(group.tripId)}&from=postcard&sourceId=${encodeURIComponent(group.id)}`}>查看这次旅行</Link> : null}
      </header>

      {/* 轮播：横向滚动 + scroll-snap，支持滑动 */}
      <div
        ref={trackRef}
        onScroll={onScroll}
        className="viewer-track"
      >
        {group.postcards.map((pc) => (
          <div
            key={pc.id}
            className="viewer-slide"
          >
            <img
              src={resolveAssetUrl(pc.imageUrl) || PLACEHOLDER_IMAGE}
              alt={pc.title}
              draggable={false}
              className="viewer-image"
              onContextMenu={(event) => event.preventDefault()}
              onPointerDown={(event) => startLongPress(event, pc)}
              onPointerMove={moveLongPress}
              onPointerUp={cancelLongPress}
              onPointerCancel={cancelLongPress}
              onPointerLeave={cancelLongPress}
              onError={handleImageError}
            />
          </div>
        ))}
      </div>

      {/* 图片浏览与显式保存入口 */}
      <div className="viewer-caption">
        <p className="viewer-location">
          <MapPin className="size-3.5" aria-hidden />
          {[place, group.dateLabel].filter(Boolean).join(" · ")}
        </p>
        <h2 className="viewer-title">{current?.title}</h2>
        <div className="viewer-dots">
          {group.postcards.map((pc, i) => (
            <button
              key={pc.id}
              type="button"
              aria-label={`查看第 ${i + 1} 张`}
              onClick={() => {
                const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"
                trackRef.current?.scrollTo({ left: i * (trackRef.current?.clientWidth ?? 0), behavior })
              }}
              className="ui-icon-button grid size-11 place-items-center rounded-full"
            >
              <span className={`h-1.5 rounded-full transition-all ${i === active ? "w-6 bg-primary" : "w-1.5 bg-muted-foreground/40"}`} />
            </button>
          ))}
        </div>
        <button className="viewer-save" disabled={!current || saving} onClick={() => setPendingSave(current)}><Download size={16} />保存明信片</button>
      </div>

      <ConfirmDialog
        open={!!pendingSave}
        title="保存这张明信片？"
        description="手机端保存到相册，网页端下载原图。"
        icon={
          <span className="grid size-12 place-items-center rounded-full bg-primary/12 text-primary">
            <Download className="size-6" aria-hidden />
          </span>
        }
        onClose={() => {
          if (!saving) setPendingSave(null)
        }}
        actions={[
          {
            label: saving ? "正在保存…" : "保存图片",
            onClick: () => {
              if (!pendingSave || saving) return
              setSaving(true)
              const imageUrl = resolveAssetUrl(pendingSave.imageUrl) || PLACEHOLDER_IMAGE
              void savePostcardImage(imageUrl, pendingSave.title)
                .then(() => {
                  setPendingSave(null)
                  toast("明信片已保存", "success")
                })
                .catch(() => toast("保存失败，请稍后重试", "error"))
                .finally(() => setSaving(false))
            },
          },
          {
            label: "取消",
            variant: "ghost",
            onClick: () => {
              if (!saving) setPendingSave(null)
            },
          },
        ]}
      />
    </div>
  )
}
