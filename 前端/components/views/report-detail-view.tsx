"use client"

import { useState, type CSSProperties, type ReactNode } from "react"
import Link from "next/link"
import { ArrowUpRight, ChevronLeft, Download, FileText, Trash2 } from "lucide-react"
import { useSearchParams } from "next/navigation"
import { ConfirmDialog } from "@/components/shared/confirm-dialog"
import { EmptyState } from "@/components/shared/empty-state"
import { useApp } from "@/components/shared/app-context"
import { PLACEHOLDER_IMAGE, handleImageError, resolveAssetUrl } from "@/lib/asset"
import { saveTravelImageBlob } from "@/lib/postcard-save"
import type { Report, TravelProfileData } from "@/types"

type ThemeStyle = CSSProperties & Record<`--${string}`, string>
type UnknownRecord = Record<string, unknown>
type ReportWithAlias = Report & { profile_data?: unknown }

interface ReportData {
  impression: string
  tags: string[]
  reasons: Array<{ title: string; detail: string }>
  requirements: string[]
  suggestions: Array<{ title: string; detail: string; prompt: string }>
  lowSample: boolean
  hasStructuredContent: boolean
}

const REPORT_STYLE: ThemeStyle = {
  "--profile-accent": "#0071e3", "--profile-accent-2": "#64a9ed",
  "--profile-glow": "#dbeafa", "--profile-bg": "#f5f5f7",
  "--profile-paper": "#ffffff", "--profile-paper-alt": "#f0f0f3",
  "--profile-ink": "#1d1d1f", "--profile-muted": "#6e6e73",
  "--profile-line": "rgba(29,29,31,.12)", "--profile-stamp": "#0071e3",
  "--foreground": "#1d1d1f", "--muted-foreground": "#6e6e73",
  "--border": "rgba(29,29,31,.12)", "--primary": "#0071e3",
}

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

  const data = buildReportData(report)
  const location = displayLocation(report.location)
  const sourceImages = unique(report.sourceImages ?? [])
  const extraImages = sourceImages.filter((image) => image !== report.coverImage).slice(0, 12)
  const regenerateHref = report.tripId
    ? `/create?tripId=${encodeURIComponent(report.tripId)}&mode=report`
    : "/create?mode=report"
  const isLegacyReport = (report.profileVersion ?? 0) < 3
  const deleting = deletingId === report.id
  let visibleSectionIndex = 0
  const nextSectionIndex = () => String(++visibleSectionIndex).padStart(2, "0")

  const startPlanning = (prompt: string, title: string) => {
    beginNewPlan(null)
    startPlanningFromSeed({
      text: prompt,
      sourceLabel: `旅行报告「${title}」`,
      returnHref: `/reports/detail?reportId=${encodeURIComponent(report.id)}`,
    })
    navigate({ page: "planning" })
  }

  const download = async () => {
    if (exporting) return
    setExporting(true)
    try {
      const blob = await renderReportImage(report, data)
      await saveTravelImageBlob(blob, `${report.location}-旅行报告`, "旅行报告")
      toast("图片已下载", "success")
    } catch {
      toast("下载失败，请重试", "error")
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="persona-report persona-editorial-report flex min-h-0 flex-1 flex-col" style={REPORT_STYLE}>
      <button type="button" onClick={() => goBackTo(backHref)} className="ui-icon-button persona-back-button" aria-label={backLabel}>
        <ChevronLeft className="size-5" aria-hidden />
      </button>
      <div className="absolute right-4 top-3 z-20 flex gap-2">
        <button type="button" onClick={() => void download()} disabled={exporting}
          className="ui-pressable flex min-h-11 items-center gap-2 rounded-lg border border-border bg-card px-3 text-xs font-semibold">
          <Download className="size-4" aria-hidden />{exporting ? "下载中…" : "下载图片"}
        </button>
        <button type="button" onClick={() => setConfirmDelete(true)}
          className="ui-icon-button grid size-11 place-items-center rounded-lg border border-border bg-card text-muted-foreground"
          aria-label="删除报告">
          <Trash2 className="size-4" aria-hidden />
        </button>
      </div>

      <div className="persona-export-sheet">
        <header className="persona-editorial-header">
          <div className="persona-cover">
            <img src={resolveAssetUrl(report.coverImage) || PLACEHOLDER_IMAGE} alt={report.location} onError={handleImageError} />
          </div>
          <p className="persona-editorial-kicker">旅行报告</p>
          {report.dateLabel || sourceImages.length || report.tripId ? <div className="persona-editorial-meta">
            {report.dateLabel ? <span>{report.dateLabel}</span> : null}
            {report.dateLabel && sourceImages.length ? <i aria-hidden /> : null}
            {sourceImages.length ? <span>{sourceImages.length} 张照片</span> : null}
            {(report.dateLabel || sourceImages.length) && report.tripId ? <i aria-hidden /> : null}
            {report.tripId ? <Link href={`/trips/detail?tripId=${encodeURIComponent(report.tripId)}&from=report&sourceId=${encodeURIComponent(report.id)}`}>查看这次旅行</Link> : null}
          </div> : null}
          <h1>{location}</h1>
          {data.lowSample ? <p className="persona-editorial-subtitle">照片较少，内容仅供参考。</p> : null}
        </header>

        {data.hasStructuredContent ? <main className="persona-report-content persona-editorial-content has-profile">
          {extraImages.length ? <ReportSection index={nextSectionIndex()} title="旅行照片">
            <ReportPhotoGrid images={extraImages} />
          </ReportSection> : null}

          {data.impression || data.tags.length ? <ReportSection index={nextSectionIndex()} title="照片内容">
            <div className="report-observation-card">
              {data.impression ? <p className="!mt-0 text-base leading-8">{data.impression}</p> : null}
              {data.tags.length ? <div className="persona-keywords mt-4">
                {data.tags.map((tag) => <span key={tag}>{tag}</span>)}
              </div> : null}
            </div>
          </ReportSection> : null}

          {data.reasons.length ? <ReportSection index={nextSectionIndex()} title="照片细节">
            <div className="persona-evidence-highlight-list">
              {data.reasons.map((item, index) => (
                <article key={`${item.title}-${index}`} className="persona-evidence-highlight-card">
                  <div><span>{String(index + 1).padStart(2, "0")}</span><strong>{item.title}</strong></div>
                  {item.detail ? <p>{item.detail}</p> : null}
                </article>
              ))}
            </div>
          </ReportSection> : null}

          {data.requirements.length ? <ReportSection index={nextSectionIndex()} title="你填写的要求">
            <ul className="grid gap-2 pl-5 text-sm leading-7">
              {data.requirements.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
            </ul>
          </ReportSection> : null}

          {data.suggestions.length ? <ReportSection index={nextSectionIndex()} title="从照片找下一站">
            <div className="persona-experiment-grid">
              {data.suggestions.map((item, index) => (
                <article key={`${item.title}-${index}`} className="persona-experiment-card">
                  <div className="persona-experiment-head"><h3>{item.title}</h3></div>
                  {item.detail ? <p>{item.detail}</p> : null}
                  {item.prompt ? <button type="button" className="report-plan-button"
                    onClick={() => startPlanning(item.prompt, item.title)}>
                    查找目的地 <ArrowUpRight className="size-4" aria-hidden />
                  </button> : null}
                </article>
              ))}
            </div>
          </ReportSection> : null}
        </main> : extraImages.length ? <main className="persona-report-content persona-editorial-content">
          <ReportSection index="01" title="旅行照片">
            <ReportPhotoGrid images={extraImages} />
          </ReportSection>
        </main> : sourceImages.length ? null : <main className="persona-report-content persona-editorial-content">
          <ReportSection index="01" title="报告内容">
            <div className="report-explicit-empty">
              <p>本次仅保留了封面与时间。</p>
              <Link href={regenerateHref}>重新生成报告</Link>
            </div>
          </ReportSection>
        </main>}
        {isLegacyReport && sourceImages.length ? (
          <div className="report-regenerate-row">
            <Link href={regenerateHref}>重新生成报告 <ArrowUpRight className="size-4" aria-hidden /></Link>
          </div>
        ) : null}
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

function ReportSection({ index, title, children }: { index: string; title: string; children: ReactNode }) {
  return <section className="persona-section persona-reveal">
    <div className="persona-section-heading"><span>{index}</span><h2>{title}</h2></div>{children}
  </section>
}

function ReportPhotoGrid({ images }: { images: string[] }) {
  return <div className="report-photo-grid">
    {images.map((image, index) => (
      <img
        key={image}
        src={resolveAssetUrl(image)}
        alt={`旅行照片 ${index + 1}`}
        onError={handleImageError}
      />
    ))}
  </div>
}

function buildReportData(report: Report): ReportData {
  const profile = getProfile(report)
  const isV3 = (report.profileVersion ?? 0) >= 3
  if (!isV3) {
    return {
      impression: "",
      tags: [],
      reasons: [],
      requirements: [],
      suggestions: [],
      lowSample: false,
      hasStructuredContent: false,
    }
  }

  const highlights = profile?.evidenceHighlights ?? []
  const impression = [profile?.sceneSignature?.description, profile?.summary]
    .map((item) => concreteText(item, 220)).find(Boolean) ?? ""
  const tags = unique((profile?.sceneSignature?.tokens ?? profile?.keywords ?? [])
    .map((item) => concreteText(item, 20))).slice(0, 4)
  const reasons = unique(highlights.map((item) => concreteText(item.observedFact, 80)))
    .slice(0, 6).map((title) => ({ title, detail: "" }))
  const requirements = unique((profile?.explicitRequirements ?? []).map((item) => plainText(item, 120)))
  const suggestions = (profile?.nextTripExperiments ?? []).slice(0, 3).map((item) => ({
    title: concreteText(item.title, 54) || "行程建议",
    detail: concreteText(item.reason, 150),
    prompt: plainText(item.planningPrompt, 300),
  })).filter((item) => item.detail || item.prompt)
  const hasStructuredContent = Boolean(impression || tags.length || reasons.length || requirements.length || suggestions.length)
  return {
    impression, tags, reasons, requirements, suggestions,
    lowSample: profile?.sampleQuality === "low",
    hasStructuredContent,
  }
}

function getProfile(report: Report): TravelProfileData | null {
  const value = report.profileData ?? (report as ReportWithAlias).profile_data
  return isRecord(value) ? camelize(value) as TravelProfileData : null
}

function plainText(value: unknown, limit = 180) {
  const text = typeof value === "string" ? value : ""
  const cleaned = text.replace(/\*\*|__|`/g, "").replace(/^\s*[:：|｜]+\s*/, "").replace(/\s+/g, " ").trim()
  return cleaned.length > limit ? `${cleaned.slice(0, limit - 1)}…` : cleaned
}

function concreteText(value: unknown, limit = 180) {
  const text = plainText(value, limit)
  return /人格|画像|性格|取景签名|旅行偏好|偏好报告|旅行处方|置信度|待验证|证据|光影|温度|松弛|氛围|诗意|治愈|小确幸|浪漫|专属|灵动|美好|审美|质感|偏好/.test(text)
    ? ""
    : text
}

function unique(items: string[]) { return [...new Set(items.filter(Boolean))] }
function displayLocation(value: string) {
  const location = value.trim()
  return !location || location === "未知地点" || location === "未知目的地" ? "未命名旅行" : location
}
function isRecord(value: unknown): value is UnknownRecord { return typeof value === "object" && value !== null }
function camelize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camelize)
  if (!isRecord(value)) return value
  return Object.fromEntries(Object.entries(value).map(([key, child]) => [
    key.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase()), camelize(child),
  ]))
}

async function renderReportImage(report: Report, data: ReportData): Promise<Blob> {
  const contentSections: Array<[string, string]> = []
  if (data.hasStructuredContent) {
    const photoContent = [data.impression, data.tags.join("、")].filter(Boolean).join("\n")
    if (photoContent) contentSections.push(["照片内容", photoContent])
    if (data.reasons.length) {
      contentSections.push(["照片细节", data.reasons.map((item) => (
        `${item.title}${item.detail ? `：${item.detail}` : ""}`
      )).join("\n")])
    }
    if (data.requirements.length) contentSections.push(["你填写的要求", data.requirements.join("\n")])
    if (data.suggestions.length) {
      contentSections.push(["从照片找下一站", data.suggestions.map((item) => (
        `${item.title}${item.detail ? `：${item.detail}` : ""}`
      )).join("\n")])
    }
  } else {
    const sourceCount = report.sourceImages?.length ?? 0
    contentSections.push(["旅行照片", sourceCount ? `共 ${sourceCount} 张照片。` : "本次仅保留了封面与时间。"])
  }
  const sections = contentSections.map(([title, body], index) => [
    `${String(index + 1).padStart(2, "0")}  ${title}`,
    body,
  ] as const)
  const estimatedBodyHeight = sections.reduce((total, [, body]) => total + 104 + estimateWrappedLines(body, 30) * 38, 0)
  const cover = await loadCanvasImage(resolveAssetUrl(report.coverImage)).catch(() => null)
  const headerHeight = cover ? 800 : 360
  const canvas = document.createElement("canvas")
  canvas.width = 1080
  canvas.height = Math.max(1600, headerHeight + estimatedBodyHeight)
  const context = canvas.getContext("2d")
  if (!context) throw new Error("无法生成图片")
  context.fillStyle = "#f5f5f7"; context.fillRect(0, 0, canvas.width, canvas.height)
  let headerY = 104
  if (cover) {
    drawImageCover(context, cover, 84, 72, 912, 480, 30)
    headerY = 620
  }
  context.fillStyle = "#0071e3"; context.font = "600 28px sans-serif"; context.fillText("旅行报告", 84, headerY)
  context.fillStyle = "#1d1d1f"; context.font = "700 62px sans-serif"; context.fillText(displayLocation(report.location), 84, headerY + 86)
  context.fillStyle = "#6e6e73"; context.font = "26px sans-serif"; context.fillText(report.dateLabel, 84, headerY + 134)
  const contentY = headerY + 188
  let y = data.lowSample ? drawWrapped(context, "照片较少，内容仅供参考。", 84, contentY, 912, 36, "#6e6e73") + 36 : contentY
  for (const [title, body] of sections) {
    context.fillStyle = "#0071e3"; context.font = "600 25px sans-serif"; context.fillText(title, 84, y); y += 48
    y = drawWrapped(context, body, 84, y, 912, 38, "#1d1d1f") + 56
  }
  return await new Promise((resolve, reject) => canvas.toBlob(
    (blob) => blob ? resolve(blob) : reject(new Error("无法生成图片")), "image/png",
  ))
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

function drawImageCover(
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight)
  const sourceWidth = width / scale
  const sourceHeight = height / scale
  const sourceX = (image.naturalWidth - sourceWidth) / 2
  const sourceY = (image.naturalHeight - sourceHeight) / 2
  context.save()
  context.beginPath()
  context.roundRect(x, y, width, height, radius)
  context.clip()
  context.drawImage(image, sourceX, sourceY, sourceWidth, sourceHeight, x, y, width, height)
  context.restore()
}

function estimateWrappedLines(text: string, charsPerLine: number) {
  return text.split("\n").reduce(
    (total, paragraph) => total + Math.max(1, Math.ceil([...paragraph].length / charsPerLine)) + 1,
    0,
  )
}

function drawWrapped(context: CanvasRenderingContext2D, text: string, x: number, y: number,
  width: number, lineHeight: number, color: string) {
  context.fillStyle = color; context.font = "28px sans-serif"
  for (const paragraph of text.split("\n")) {
    let line = ""
    for (const char of paragraph) {
      if (context.measureText(line + char).width > width) {
        context.fillText(line, x, y); line = char; y += lineHeight
      } else line += char
    }
    if (line) context.fillText(line, x, y)
    y += lineHeight
  }
  return y
}
