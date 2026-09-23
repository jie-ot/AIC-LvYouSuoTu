"use client"

import { useState, type CSSProperties, type ReactNode } from "react"
import Link from "next/link"
import { ArrowUpRight, ChevronLeft, FileText, Share2, Trash2 } from "lucide-react"
import { useSearchParams } from "next/navigation"
import { ConfirmDialog } from "@/components/shared/confirm-dialog"
import { EmptyState } from "@/components/shared/empty-state"
import { useApp } from "@/components/shared/app-context"
import { PLACEHOLDER_IMAGE, handleImageError, resolveAssetUrl } from "@/lib/asset"
import { displayPlace } from "@/lib/place"
import { saveTravelImageBlob } from "@/lib/postcard-save"
import type {
  JourneyStat, NextStop, PaletteColor, PersonaAxis, Report, TravelProfileData,
} from "@/types"

type ThemeStyle = CSSProperties & Record<`--${string}`, string>
type UnknownRecord = Record<string, unknown>
type ReportWithAlias = Report & { profile_data?: unknown }

interface PersonaView {
  code: string
  name: string
  tagline: string
  title: string
  route: string[]
  chips: string[]
  kicker: string
  portrait: string
  word: string
  wordNote: string
  evolution: string
  axes: PersonaAxis[]
  stats: JourneyStat[]
  palette: PaletteColor[]
  frame: { imageUrl: string; caption: string; meta: string } | null
  nextStops: NextStop[]
}

const SEAL_RED = "#b83a2b"
const FALLBACK_ACCENT: Record<string, string> = {
  forest_light: "#3f6b4f", ocean_blue: "#1f6f8b", sunset_orange: "#b5562f",
  museum_gold: "#8a6a30", city_neon: "#5a46a8", night_purple: "#474084",
}
const DISPLAY_FONT = `"Noto Serif CJK SC", "Source Han Serif SC", "Songti SC", "SimSun", serif`
const SANS_FONT = `"Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei UI", system-ui, sans-serif`

export function ReportDetailView() {
  const searchParams = useSearchParams()
  const {
    reports, goBackTo, navigate, toast, deleteReport, deletingId,
    beginNewPlan, startPlanningFromSeed,
  } = useApp()
  const reportId = searchParams.get("reportId") ?? ""
  const report = reports.find((item) => item.id === reportId)
  const returnTripId = searchParams.get("tripId") ?? report?.tripId
  const backHref = searchParams.get("from") === "trip" && returnTripId
    ? `/trips/detail?tripId=${encodeURIComponent(returnTripId)}`
    : "/reports"
  const backLabel = returnTripId && searchParams.get("from") === "trip" ? "返回这次旅行" : "返回旅行报告"
  const [exporting, setExporting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  if (!report) {
    return (
      <div className="flex flex-1 flex-col">
        <EmptyState
          icon={<FileText className="size-7" aria-hidden />}
          title="报告不存在"
          description="这份旅行报告不存在或已删除。"
        >
          <button type="button" onClick={() => goBackTo(backHref)} className="primary-action">{backLabel}</button>
        </EmptyState>
      </div>
    )
  }

  const profile = getProfile(report)
  const view = profile?.axes?.length === 4 ? buildPersonaView(report, profile) : null
  const deleting = deletingId === report.id
  const regenerateHref = report.tripId
    ? `/create?tripId=${encodeURIComponent(report.tripId)}&mode=report`
    : "/create?mode=report"
  const accent = view ? pickAccent(view.palette, profile?.visualTheme) : "#6e6a62"
  const style = themeStyle(accent, view?.palette ?? [])

  const startPlanning = (prompt: string, destination: string) => {
    beginNewPlan(null)
    startPlanningFromSeed({
      text: prompt,
      sourceLabel: `旅格锦囊「${destination}」`,
      returnHref: `/reports/detail?reportId=${encodeURIComponent(report.id)}`,
    })
    navigate({ page: "planning" })
  }

  const exportPoster = async () => {
    if (exporting || !view) return
    setExporting(true)
    try {
      const blob = await renderPoster(report, view, accent)
      await saveTravelImageBlob(blob, `${view.title}-${view.name}`, "旅格分享图")
      toast("分享图已保存", "success")
    } catch {
      toast("保存失败，请重试", "error")
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="lg-report" style={style}>
      <div className="lg-toolbar">
        <button type="button" onClick={() => goBackTo(backHref)} className="lg-tool-button" aria-label={backLabel}>
          <ChevronLeft className="size-5" aria-hidden />
        </button>
        <div className="lg-toolbar-actions">
          {view ? <button type="button" onClick={() => void exportPoster()} disabled={exporting} className="lg-tool-button is-wide">
            <Share2 className="size-4" aria-hidden />{exporting ? "生成中…" : "分享图"}
          </button> : null}
          <button type="button" onClick={() => setConfirmDelete(true)} className="lg-tool-button" aria-label="删除报告">
            <Trash2 className="size-4" aria-hidden />
          </button>
        </div>
      </div>

      <div className="lg-scroll">
        {view ? <PersonaReport report={report} view={view} onPlan={startPlanning} /> : (
          <LegacyReport report={report} regenerateHref={regenerateHref} />
        )}
      </div>

      <ConfirmDialog open={confirmDelete} title="删除这份旅行报告？" description="删除后无法恢复。"
        onClose={() => !deleting && setConfirmDelete(false)} actions={[
          { label: deleting ? "删除中…" : "删除", variant: "danger", onClick: () => {
            if (!deleting) void deleteReport(report.id).then(() => goBackTo(backHref))
          } },
          { label: "取消", variant: "ghost", onClick: () => setConfirmDelete(false) },
        ]} />
    </div>
  )
}

function PersonaReport({ report, view, onPlan }: {
  report: Report
  view: PersonaView
  onPlan: (prompt: string, destination: string) => void
}) {
  const cover = resolveAssetUrl(view.frame?.imageUrl || report.coverImage) || PLACEHOLDER_IMAGE
  const sourceImages = unique(report.sourceImages ?? []).filter((image) => image !== view.frame?.imageUrl)
  return <>
    <header className="lg-hero">
      <img src={cover} alt={view.title} onError={handleImageError} />
      <div className="lg-hero-shade" aria-hidden />
      <div className="lg-hero-copy">
        <p className="lg-kicker">{view.kicker}</p>
        <h1>{view.title}</h1>
        {view.route.length ? <p className="lg-route">{view.route.join(" → ")}</p> : null}
      </div>
      {view.frame ? <figure className="lg-hero-label">
        <span>高光一帧</span>
        <p>{view.frame.caption}</p>
        {view.frame.meta ? <small>{view.frame.meta}</small> : null}
      </figure> : null}
    </header>

    <section className="lg-identity">
      <Seal code={view.code} />
      <div className="lg-identity-copy">
        <span>这一程，你是</span>
        <h2>{view.name}</h2>
        <p>{view.tagline}</p>
      </div>
      {view.chips.length ? <div className="lg-chips">{view.chips.map((chip) => <span key={chip}>{chip}</span>)}</div> : null}
      {report.tripId ? <Link className="lg-trip-link" href={`/trips/detail?tripId=${encodeURIComponent(report.tripId)}&from=report&sourceId=${encodeURIComponent(report.id)}`}>
        查看这次旅行 <ArrowUpRight className="size-3.5" aria-hidden />
      </Link> : null}
    </section>

    <main className="lg-body">
      {view.portrait ? <Section index="01" title="旅格侧写">
        <div className="lg-portrait">
          <p>{view.portrait}</p>
          {view.word ? <aside className="lg-word" aria-label={`本程一字：${view.word}`}>
            <small>本程一字</small>
            <b>{view.word}</b>
            {view.wordNote ? <span>{view.wordNote}</span> : null}
          </aside> : null}
        </div>
        {view.evolution ? <p className="lg-evolution">{view.evolution}</p> : null}
      </Section> : null}

      <Section index="02" title="旅格四象" note={view.code}>
        <div className="lg-axes">
          {view.axes.map((axis) => <AxisRow key={axis.id} axis={axis} />)}
        </div>
      </Section>

      {view.stats.length ? <Section index="03" title="此行之最">
        <div className="lg-stats">
          {view.stats.map((stat) => <article key={stat.id} className={stat.imageUrl ? "has-photo" : undefined}>
            {stat.imageUrl ? <img src={resolveAssetUrl(stat.imageUrl)} alt="" onError={handleImageError} loading="lazy" /> : null}
            <span>{stat.label}</span>
            <strong>{stat.value}{stat.unit ? <small>{stat.unit}</small> : null}</strong>
            {stat.caption ? <p>{stat.caption}</p> : null}
          </article>)}
        </div>
      </Section> : null}

      {view.palette.length ? <Section index="04" title="此行色谱" note={`主色 · ${view.palette[0].name}`}>
        <div className="lg-palette-bar" aria-hidden>
          {view.palette.map((color) => <i key={color.name} style={{ flex: Math.max(4, color.share), background: color.hex }} />)}
        </div>
        <div className="lg-swatches">
          {view.palette.map((color) => <figure key={color.name}>
            <i style={{ background: color.hex }} aria-hidden />
            <figcaption><b>{color.name}</b><small>{color.share}%</small></figcaption>
          </figure>)}
        </div>
        {sourceImages.length ? <div className="lg-contact" aria-label="参与计算的照片">
          {sourceImages.slice(0, 10).map((image) => <img key={image} src={resolveAssetUrl(image)} alt="" loading="lazy" onError={handleImageError} />)}
        </div> : null}
      </Section> : null}

      {view.nextStops.length ? <Section index="05" title="下一站锦囊">
        <div className="lg-next">
          {view.nextStops.map((stop) => <article key={stop.kind}>
            <span>{stop.kind === "continue" ? "顺着走" : "反着来"}</span>
            <h3>{stop.destination}</h3>
            <strong>{stop.title}</strong>
            <p>{stop.reason}</p>
            {stop.planningPrompt ? <button type="button" onClick={() => onPlan(stop.planningPrompt, stop.destination)}>
              按这个旅格规划 <ArrowUpRight className="size-4" aria-hidden />
            </button> : null}
          </article>)}
        </div>
      </Section> : null}
    </main>
  </>
}

function LegacyReport({ report, regenerateHref }: { report: Report; regenerateHref: string }) {
  const images = unique(report.sourceImages ?? []).slice(0, 12)
  const title = displayPlace(report.location, report.personalitySummary)
  return <div className="lg-legacy">
    <img className="lg-legacy-cover" src={resolveAssetUrl(report.coverImage) || PLACEHOLDER_IMAGE} alt={title} onError={handleImageError} />
    <div className="lg-legacy-copy">
      <p className="lg-kicker is-dark">{report.dateLabel}</p>
      <h1>{title}</h1>
      <p>这份报告生成于旧版本。用同一组照片重新生成，就能拿到你的四字旅格码、此行之最和旅途色谱。</p>
      <Link href={regenerateHref} className="primary-action">重新生成旅格 <ArrowUpRight className="size-4" aria-hidden /></Link>
    </div>
    {images.length ? <div className="lg-contact is-grid">
      {images.map((image) => <img key={image} src={resolveAssetUrl(image)} alt="" loading="lazy" onError={handleImageError} />)}
    </div> : null}
  </div>
}

function Section({ index, title, note, children }: { index: string; title: string; note?: string; children: ReactNode }) {
  return <section className="lg-section">
    <header><span>{index}</span><h2>{title}</h2>{note ? <em>{note}</em> : null}</header>
    {children}
  </section>
}

function Seal({ code, size = "large", variant = "solid" }: {
  code: string
  size?: "large" | "small"
  variant?: "solid" | "outline"
}) {
  return <span className={`lg-seal is-${size} is-${variant}`} role="img" aria-label={`旅格码 ${code}`}>
    {[...code].slice(0, 4).map((char, index) => <i key={`${char}-${index}`}>{char}</i>)}
  </span>
}

function AxisRow({ axis }: { axis: PersonaAxis }) {
  const leansRight = axis.value > 50
  const percent = leansRight ? axis.value : 100 - axis.value
  const label = leansRight ? axis.rightLabel : axis.leftLabel
  return <div className="lg-axis">
    <span className="lg-axis-name">{axis.name}</span>
    <div className="lg-axis-body">
      <div className="lg-axis-track">
        <b className={leansRight ? undefined : "is-on"}>{axis.leftPole}</b>
        <div className="lg-axis-bar">
          <i style={{ left: `${Math.max(3, Math.min(97, axis.value))}%` }} />
        </div>
        <b className={leansRight ? "is-on" : undefined}>{axis.rightPole}</b>
      </div>
      <p><strong>{percent}% {label}</strong>{axis.evidence ? <small>{axis.evidence}</small> : null}</p>
    </div>
  </div>
}

function buildPersonaView(report: Report, profile: TravelProfileData): PersonaView {
  const journey = profile.journey
  const code = plainText(profile.personaCode, 8)
  const count = Math.max(1, Number(profile.journeyCount ?? 1))
  const chips = [
    journey?.dayCount ? `${journey.dayCount} 天` : "",
    journey && journey.cityCount > 1 ? `${journey.cityCount} 站` : "",
    journey?.pathKm ? `首尾 ${journey.pathKm.toLocaleString("zh-CN")} km` : "",
  ].filter(Boolean)
  const frame = profile.signatureFrame
  const frameMeta = [frame?.moment, frame?.place].filter(Boolean).join(" · ")
  const previous = plainText(profile.evolutionFrom, 8)
  const evolution = !previous ? "" : previous === code
    ? `连续两程都是「${code}」，这份旅格越来越稳了。`
    : `上一程是「${previous}」，这一程换成了「${code}」。`
  return {
    code,
    name: plainText(profile.archetypeName, 12),
    tagline: plainText(profile.slogan, 40),
    title: plainText(journey?.title, 20) || displayPlace(report.location, profile.archetypeName),
    route: (journey?.route ?? []).map((item) => plainText(item, 12)).filter(Boolean).slice(0, 6),
    chips,
    kicker: [`旅格 No.${String(count).padStart(2, "0")}`, report.dateLabel].filter(Boolean).join(" · "),
    portrait: plainText(profile.summary, 140),
    word: plainText(profile.tripWord, 1),
    wordNote: plainText(profile.tripWordNote, 24),
    evolution,
    axes: profile.axes ?? [],
    stats: (profile.stats ?? []).slice(0, 3),
    palette: (profile.palette ?? []).filter((color) => /^#[0-9a-f]{6}$/i.test(color.hex)).slice(0, 5),
    frame: frame ? {
      imageUrl: frame.imageUrl || report.coverImage,
      caption: plainText(frame.caption, 40),
      meta: frameMeta,
    } : null,
    nextStops: (profile.nextStops ?? []).slice(0, 2),
  }
}

function getProfile(report: Report): TravelProfileData | null {
  const value = report.profileData ?? (report as ReportWithAlias).profile_data
  return isRecord(value) ? camelize(value) as TravelProfileData : null
}

function plainText(value: unknown, limit = 180) {
  const text = typeof value === "string" ? value : ""
  const cleaned = text.replace(/\*\*|__|`/g, "").replace(/\s+/g, " ").trim()
  return [...cleaned].length > limit ? `${[...cleaned].slice(0, limit - 1).join("")}…` : cleaned
}

function unique(items: string[]) { return [...new Set(items.filter(Boolean))] }
function isRecord(value: unknown): value is UnknownRecord { return typeof value === "object" && value !== null }
function camelize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camelize)
  if (!isRecord(value)) return value
  return Object.fromEntries(Object.entries(value).map(([key, child]) => [
    key.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase()), camelize(child),
  ]))
}

/* ---------------- theme ---------------- */

function hexToHsl(hex: string): [number, number, number] {
  const [r, g, b] = [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16) / 255)
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const lightness = (max + min) / 2
  if (max === min) return [0, 0, lightness]
  const delta = max - min
  const saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min)
  const hue = max === r ? (g - b) / delta + (g < b ? 6 : 0) : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4
  return [hue * 60, saturation, lightness]
}

function hslToHex(hue: number, saturation: number, lightness: number) {
  const k = (n: number) => (n + hue / 30) % 12
  const a = saturation * Math.min(lightness, 1 - lightness)
  const channel = (n: number) => Math.round(255 * (lightness - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))))
  return `#${[0, 8, 4].map((n) => channel(n).toString(16).padStart(2, "0")).join("")}`
}

/** The most characterful palette colour, deepened until white text reads on it. */
function pickAccent(palette: PaletteColor[], theme?: string) {
  const scored = palette
    .map((color) => ({ color, hsl: hexToHsl(color.hex) }))
    .filter(({ hsl }) => hsl[1] >= 0.18)
    .sort((a, b) => (b.hsl[1] * (1 - Math.abs(b.hsl[2] - 0.45)) + b.color.share / 400)
      - (a.hsl[1] * (1 - Math.abs(a.hsl[2] - 0.45)) + a.color.share / 400))
  if (!scored.length) return FALLBACK_ACCENT[theme ?? ""] ?? "#6e5a3c"
  const [hue, saturation, lightness] = scored[0].hsl
  return hslToHex(hue, Math.min(0.62, Math.max(0.32, saturation)), Math.min(0.4, Math.max(0.28, lightness)))
}

function themeStyle(accent: string, palette: PaletteColor[]): ThemeStyle {
  const [first, second] = [palette[0]?.hex ?? accent, palette[1]?.hex ?? palette[0]?.hex ?? accent]
  return {
    "--lg-accent": accent,
    "--lg-seal": SEAL_RED,
    "--lg-aura-1": first,
    "--lg-aura-2": second,
  }
}

/* ---------------- share poster (1080 × 1920) ---------------- */

async function renderPoster(report: Report, view: PersonaView, accent: string): Promise<Blob> {
  const width = 1080
  const height = 1920
  const canvas = document.createElement("canvas")
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("无法生成图片")
  const ink = "#1f1d1a"
  const muted = "#6e6a62"
  ctx.fillStyle = "#f6f3ec"
  ctx.fillRect(0, 0, width, height)

  const cover = await loadCanvasImage(resolveAssetUrl(view.frame?.imageUrl || report.coverImage)).catch(() => null)
  const heroHeight = 880
  if (cover) drawCover(ctx, cover, 0, 0, width, heroHeight)
  else { ctx.fillStyle = accent; ctx.fillRect(0, 0, width, heroHeight) }
  const shade = ctx.createLinearGradient(0, heroHeight * 0.35, 0, heroHeight)
  shade.addColorStop(0, "rgba(0,0,0,0)")
  shade.addColorStop(1, "rgba(0,0,0,0.62)")
  ctx.fillStyle = shade
  ctx.fillRect(0, 0, width, heroHeight)
  const topShade = ctx.createLinearGradient(0, 0, 0, 220)
  topShade.addColorStop(0, "rgba(0,0,0,0.35)")
  topShade.addColorStop(1, "rgba(0,0,0,0)")
  ctx.fillStyle = topShade
  ctx.fillRect(0, 0, width, 220)

  ctx.fillStyle = "rgba(255,255,255,0.88)"
  ctx.font = `600 30px ${SANS_FONT}`
  ctx.fillText(view.kicker, 72, 96)
  ctx.fillStyle = "#ffffff"
  ctx.font = `700 92px ${DISPLAY_FONT}`
  const titleBottom = drawLines(ctx, view.title, 72, heroHeight - (view.route.length ? 170 : 110), width - 144, 108, 2)
  if (view.route.length) {
    ctx.fillStyle = "rgba(255,255,255,0.86)"
    ctx.font = `500 34px ${SANS_FONT}`
    drawLines(ctx, view.route.join(" → "), 72, Math.max(titleBottom + 14, heroHeight - 78), width - 144, 44, 1)
  }

  // Identity: seal + name + tagline.
  const sealSize = 196
  const sealY = heroHeight + 64
  drawSeal(ctx, view.code, 72, sealY, sealSize, SEAL_RED, "solid")
  ctx.fillStyle = muted
  ctx.font = `500 28px ${SANS_FONT}`
  ctx.fillText("这一程，你是", 310, sealY + 38)
  ctx.fillStyle = ink
  ctx.font = `700 84px ${DISPLAY_FONT}`
  ctx.fillText(view.name, 306, sealY + 132)
  ctx.fillStyle = muted
  ctx.font = `400 32px ${SANS_FONT}`
  drawLines(ctx, view.tagline, 310, sealY + 186, width - 382, 42, 2)

  // Four axes.
  let y = sealY + sealSize + 64
  for (const axis of view.axes) {
    const leansRight = axis.value > 50
    ctx.font = `600 22px ${SANS_FONT}`
    ctx.fillStyle = muted
    ctx.fillText(axis.name, 72, y)
    ctx.font = `700 36px ${DISPLAY_FONT}`
    ctx.fillStyle = leansRight ? "#b9b3a7" : ink
    ctx.fillText(axis.leftPole, 72, y + 48)
    ctx.fillStyle = leansRight ? ink : "#b9b3a7"
    const rightWidth = ctx.measureText(axis.rightPole).width
    ctx.fillText(axis.rightPole, width - 72 - rightWidth, y + 48)
    const barX = 200
    const barWidth = width - 144 - 256
    ctx.fillStyle = "#e4dfd4"
    roundRect(ctx, barX, y + 34, barWidth, 12, 6)
    ctx.fill()
    const marker = barX + (barWidth * Math.max(3, Math.min(97, axis.value))) / 100
    ctx.fillStyle = accent
    ctx.beginPath()
    ctx.arc(marker, y + 40, 12, 0, Math.PI * 2)
    ctx.fill()
    y += 96
  }

  // 此行之最.
  y += 40
  const columnWidth = (width - 144) / 3
  view.stats.forEach((stat, index) => {
    const x = 72 + index * columnWidth
    ctx.fillStyle = muted
    ctx.font = `500 26px ${SANS_FONT}`
    ctx.fillText(stat.label, x, y)
    ctx.fillStyle = ink
    ctx.font = `700 64px ${SANS_FONT}`
    ctx.fillText(stat.value, x, y + 76)
    const valueWidth = ctx.measureText(stat.value).width
    if (stat.unit) {
      ctx.font = `600 28px ${SANS_FONT}`
      ctx.fillText(stat.unit, x + valueWidth + 8, y + 76)
    }
    ctx.fillStyle = muted
    ctx.font = `400 24px ${SANS_FONT}`
    drawLines(ctx, stat.caption, x, y + 118, columnWidth - 24, 32, 2)
  })

  // 此行色谱.
  y += 200
  const palette = view.palette.length ? view.palette : [{ name: "", hex: accent, share: 100 }]
  const total = palette.reduce((sum, color) => sum + Math.max(4, color.share), 0)
  let x = 72
  for (const color of palette) {
    const segment = ((width - 144) * Math.max(4, color.share)) / total
    ctx.fillStyle = color.hex
    ctx.fillRect(x, y, segment, 40)
    if (color.name && segment > 60) {
      ctx.fillStyle = muted
      ctx.font = `500 24px ${SANS_FONT}`
      ctx.fillText(color.name, x + 4, y + 76)
    }
    x += segment
  }

  // Footer.
  ctx.fillStyle = "#e4dfd4"
  ctx.fillRect(72, height - 150, width - 144, 2)
  ctx.fillStyle = ink
  ctx.font = `600 30px ${SANS_FONT}`
  ctx.fillText("旅有所图 · 旅格", 72, height - 88)
  if (view.word) {
    ctx.fillStyle = muted
    ctx.font = `400 28px ${SANS_FONT}`
    const stamp = `本程一字 · ${view.word}`
    ctx.fillText(stamp, width - 72 - ctx.measureText(stamp).width, height - 88)
  }

  return await new Promise((resolve, reject) => canvas.toBlob(
    (blob) => blob ? resolve(blob) : reject(new Error("无法生成图片")), "image/png",
  ))
}

function drawSeal(ctx: CanvasRenderingContext2D, code: string, x: number, y: number, size: number, color: string, variant: "solid" | "outline") {
  const chars = [...code].slice(0, 4)
  ctx.save()
  roundRect(ctx, x, y, size, size, size * 0.08)
  if (variant === "solid") { ctx.fillStyle = color; ctx.fill() } else { ctx.lineWidth = 6; ctx.strokeStyle = color; ctx.stroke() }
  ctx.fillStyle = variant === "solid" ? "#fff7ef" : color
  ctx.font = `700 ${Math.round(size * 0.36)}px ${DISPLAY_FONT}`
  ctx.textAlign = "center"
  ctx.textBaseline = "middle"
  // Seals read right column first, top to bottom: 1 3 / 2 4 mirrored.
  const cells = [[0.72, 0.29], [0.72, 0.71], [0.28, 0.29], [0.28, 0.71]]
  chars.forEach((char, index) => {
    const [cx, cy] = cells[index]
    ctx.fillText(char, x + size * cx, y + size * cy + size * 0.01)
  })
  ctx.restore()
}

function drawLines(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, maxWidth: number, lineHeight: number, maxLines: number) {
  const lines: string[] = []
  let line = ""
  for (const char of [...text]) {
    if (ctx.measureText(line + char).width > maxWidth && line) {
      lines.push(line)
      line = char
      if (lines.length === maxLines) break
    } else line += char
  }
  if (line && lines.length < maxLines) lines.push(line)
  if (lines.length === maxLines && [...lines.join("")].length < [...text].length) {
    let last = lines[maxLines - 1]
    while (last && ctx.measureText(last + "…").width > maxWidth) last = last.slice(0, -1)
    lines[maxLines - 1] = `${last}…`
  }
  lines.forEach((value, index) => ctx.fillText(value, x, y + index * lineHeight))
  return y + (lines.length - 1) * lineHeight
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  ctx.beginPath()
  ctx.roundRect(x, y, width, height, radius)
}

async function loadCanvasImage(url: string): Promise<HTMLImageElement> {
  if (!url) throw new Error("没有封面")
  // 页面里的普通 <img> 可能已缓存为不带 CORS 的响应，直接复用会让
  // canvas 无法导出。重新读取为 Blob，再通过同源 object URL 绘制。
  const response = await fetch(url, { cache: "no-store", mode: "cors" })
  if (!response.ok) throw new Error("封面加载失败")
  const objectUrl = URL.createObjectURL(await response.blob())
  try {
    return await new Promise((resolve, reject) => {
      const image = new Image()
      image.onload = () => resolve(image)
      image.onerror = () => reject(new Error("封面加载失败"))
      image.src = objectUrl
    })
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
}

function drawCover(ctx: CanvasRenderingContext2D, image: HTMLImageElement, x: number, y: number, width: number, height: number) {
  const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight)
  const sourceWidth = width / scale
  const sourceHeight = height / scale
  const sourceX = (image.naturalWidth - sourceWidth) / 2
  const sourceY = (image.naturalHeight - sourceHeight) / 2
  ctx.drawImage(image, sourceX, sourceY, sourceWidth, sourceHeight, x, y, width, height)
}
