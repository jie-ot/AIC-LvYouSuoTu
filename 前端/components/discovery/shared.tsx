"use client"

import { Children, useEffect, useLayoutEffect, useRef, type ReactNode } from "react"
import { X, MapPin, Route, Images, FileText } from "lucide-react"
import { handleImageError, resolveAssetUrl } from "@/lib/asset"
import { useApp } from "@/components/shared/app-context"
import type { Attachments, DiscoveryPost } from "@/lib/discovery-api"

export function DiscoveryGrid({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const grid = ref.current
    if (!grid) return
    const tiles = Array.from(grid.children) as HTMLElement[]
    const measure = () => {
      const gap = parseFloat(getComputedStyle(grid).rowGap) || 12
      for (const tile of tiles) {
        const height = tile.firstElementChild?.getBoundingClientRect().height || 0
        tile.style.gridRowEnd = "span " + Math.ceil((height + gap) / (1 + gap))
      }
    }
    const observer = new ResizeObserver(measure)
    tiles.forEach((tile) => { if (tile.firstElementChild) observer.observe(tile.firstElementChild) })
    measure()
    return () => observer.disconnect()
  }, [children])
  return <div ref={ref} className="discovery-grid">{Children.map(children, (child) => <div className="discovery-tile" style={{ gridRowEnd: "span 35" }}>{child}</div>)}</div>
}

export function DiscoveryDialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const { registerBackHandler } = useApp()
  useEffect(() => {
    const element = ref.current
    element?.showModal()
    return () => element?.close()
  }, [])
  useEffect(() => registerBackHandler(onClose), [registerBackHandler, onClose])
  return (
    <dialog ref={ref} className="discovery-dialog" aria-label={title} onCancel={(event) => { event.preventDefault(); onClose() }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div className="discovery-dialog-inner">
        <header><h2>{title}</h2><button type="button" className="discovery-icon" onClick={onClose} aria-label="关闭"><X size={20} /></button></header>
        {children}
      </div>
    </dialog>
  )
}

export function TagPicker({ selected, tags, onChange, label, max = 12 }: { selected: string[]; tags: string[]; onChange: (value: string[]) => void; label: string; max?: number }) {
  return <div className="discovery-chips" role="group" aria-label={label}>
    {tags.map((tag) => <button type="button" key={tag} aria-pressed={selected.includes(tag)}
      disabled={!selected.includes(tag) && selected.length >= max}
      onClick={() => onChange(selected.includes(tag) ? selected.filter((item) => item !== tag) : [...selected, tag])}>{tag}</button>)}
  </div>
}

export function NoteAttachments({ attachments }: { attachments: Attachments }) {
  return <div className="note-attachments">
    {attachments.postcards?.length ? <section><h3><Images size={17} />这一程的明信片</h3><div className="note-postcards">
      {attachments.postcards.map((item) => <figure key={item.id}><img src={resolveAssetUrl(item.imageUrl)} alt={item.title} loading="lazy" onError={handleImageError} /><figcaption>{item.title}</figcaption></figure>)}
    </div></section> : null}
    {attachments.reports?.map((report) => <details key={report.id} className="note-attachment"><summary><FileText size={17} /><span>旅行人格报告 · {report.title}</span></summary>
      <p>{report.summary}</p><div className="note-report-content">{report.content}</div>
    </details>)}
    {attachments.plans?.map((plan) => <details key={plan.id} className="note-attachment"><summary><Route size={17} /><span>{plan.title} · {plan.days.length} 天路线</span></summary>
      {plan.days.length ? plan.days.map((day, index) => <div key={index} className="note-day"><strong>第 {index + 1} 天 · {day.title}</strong><p>{day.stops.filter(Boolean).join(" → ") || "当天路线待补充"}</p></div>) : <p>这份行程还没有每日路线。</p>}
    </details>)}
  </div>
}

export function NoteBody({ post }: { post: Pick<DiscoveryPost, "photos" | "title" | "destination" | "body" | "recommendations" | "pitfalls" | "tags" | "attachments" | "isDemo"> }) {
  return <>
    {post.photos.length ? <div className="note-gallery" aria-label="旅行图片">
      {post.photos.map((url, index) => <figure key={url + index}><img src={resolveAssetUrl(url)} alt={post.destination + "旅行图片 " + (index + 1)} onError={handleImageError} loading={index ? "lazy" : "eager"} /><figcaption>{index + 1} / {post.photos.length}</figcaption></figure>)}
    </div> : null}
    <div className="note-reading">
      <span className="note-location"><MapPin size={14} />{post.destination}</span>
      <h1>{post.title}</h1>
      <p className="note-prose">{post.body}</p>
      {post.recommendations ? <section className="note-advice"><h2>值得推荐</h2><p>{post.recommendations}</p></section> : null}
      {post.pitfalls ? <section className="note-advice caution"><h2>行前提醒 · 避雷</h2><p>{post.pitfalls}</p></section> : null}
      <div className="note-tags">{post.tags.map((tag) => <span key={tag}>#{tag}</span>)}</div>
      <NoteAttachments attachments={post.attachments} />
      {post.isDemo ? <p className="note-demo-notice">{post.attachments.demoNotice || "这是一篇合成演示笔记，内容不代表真实用户经历。"} 出行信息请在临行前核对。
        {post.attachments.coverCredit ? <> 封面：<a href={post.attachments.coverCredit.url} target="_blank" rel="noreferrer">{post.attachments.coverCredit.author} / Unsplash</a>。</> : null}</p> : null}
    </div>
  </>
}
