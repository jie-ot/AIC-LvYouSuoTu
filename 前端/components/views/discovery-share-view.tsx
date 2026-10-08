"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Camera, Check, FileText, Images, LoaderCircle, Route, Sparkles, X } from "lucide-react"
import { BottomNav } from "@/components/shared/bottom-nav"
import { useApp } from "@/components/shared/app-context"
import { DiscoveryDialog, NoteBody, TagPicker } from "@/components/discovery/shared"
import { handleImageError, resolveAssetUrl } from "@/lib/asset"
import { uploadImage } from "@/lib/api"
import { preparePhotoForUpload } from "@/lib/upload-photo"
import { newRequestId } from "@/lib/request-id"
import { DISCOVERY_TAGS, assistDiscoveryNote, getShareOptions, publishDiscoveryPost, type AssistResult, type ShareInput, type ShareOptions } from "@/lib/discovery-api"

function toggle(list: string[], id: string) { return list.includes(id) ? list.filter((item) => item !== id) : [...list, id] }
function emptyDraft(tripId: string): ShareInput {
  return { tripId, requestId: "", title: "", destination: "", body: "", recommendations: "", pitfalls: "", tags: [], photoAssetIds: [], reportIds: [], postcardIds: [], planIds: [] }
}

function ShareForm({ options }: { options: ShareOptions }) {
  const router = useRouter()
  const { toast, toastError } = useApp()
  const [draft, setDraft] = useState<ShareInput>(() => ({
    ...emptyDraft(options.trip.id), title: (options.trip.title + " · 旅行随记").slice(0, 60), destination: options.trip.destination,
    photoAssetIds: options.photos.slice(0, 9).map((photo) => photo.id),
  }))
  const [photos, setPhotos] = useState(options.photos)
  const [preview, setPreview] = useState(false)
  const [assisting, setAssisting] = useState(false)
  const [assisted, setAssisted] = useState<AssistResult | null>(null)
  const [uploading, setUploading] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [hydrated, setHydrated] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const requestId = useRef("")
  const draftRef = useRef(draft)
  const draftKey = "lvyousuotu:discovery-draft:" + options.trip.id
  useEffect(() => { draftRef.current = draft }, [draft])
  useEffect(() => {
    let restored: { draft?: ShareInput; photos?: { id: string; url: string }[] } | null = null
    try { restored = JSON.parse(localStorage.getItem(draftKey) || "null") } catch { /* Corrupt local drafts do not block sharing. */ }
    const task = window.setTimeout(() => {
      if (restored?.draft?.tripId === options.trip.id && Array.isArray(restored.draft.tags) && Array.isArray(restored.draft.photoAssetIds)) {
        setDraft(restored.draft)
        if (Array.isArray(restored.photos)) setPhotos(restored.photos)
      }
      requestId.current = restored?.draft?.requestId || newRequestId()
      setHydrated(true)
    }, 0)
    return () => window.clearTimeout(task)
  }, [draftKey, options.trip.id])
  useEffect(() => {
    if (!hydrated) return
    try { localStorage.setItem(draftKey, JSON.stringify({ draft: { ...draft, requestId: requestId.current }, photos })) } catch { /* Storage can be disabled. */ }
  }, [draft, photos, hydrated, draftKey])
  function field(name: "title" | "destination" | "body" | "recommendations" | "pitfalls", value: string) {
    setDraft((old) => ({ ...old, [name]: value }))
  }
  async function upload(files: FileList | null) {
    if (!files?.length || uploading) return
    const capacity = 12 - draft.photoAssetIds.length
    if (capacity <= 0) { toast("最多选择 12 张照片", "info"); return }
    if (files.length > capacity) toast("本次只添加前 " + capacity + " 张照片", "info")
    setUploading(true)
    try {
      for (const file of Array.from(files).slice(0, capacity)) {
        const result = await uploadImage(await preparePhotoForUpload(file))
        setPhotos((old) => old.some((photo) => photo.id === result.assetId) ? old : [...old, { id: result.assetId, url: result.imageUrl }])
        setDraft((old) => ({ ...old, photoAssetIds: Array.from(new Set([...old.photoAssetIds, result.assetId])).slice(0, 12) }))
      }
    } catch (error) { toastError(error) } finally { setUploading(false); if (fileInput.current) fileInput.current.value = "" }
  }
  async function assist() {
    if (assisting) return
    const current = draftRef.current
    setAssisting(true)
    try {
      const result = await assistDiscoveryNote(current)
      const textFields = ["title", "destination", "body", "recommendations", "pitfalls"] as const
      if (textFields.every((key) => draftRef.current[key] === current[key])) setAssisted(result)
      else toast("文字已修改，请按最新内容重新整理", "info")
    } catch (error) { toastError(error) } finally { setAssisting(false) }
  }
  async function publish() {
    if (publishing || uploading) return
    setPublishing(true)
    try {
      const result = await publishDiscoveryPost({ ...draft, requestId: requestId.current })
      try { localStorage.removeItem(draftKey) } catch { /* optional local cache */ }
      toast("旅行笔记已发布", "success")
      router.replace("/discover/detail?postId=" + encodeURIComponent(result.id))
    } catch (error) { toastError(error); setPublishing(false) }
  }
  const attachments = {
    reports: options.reports.filter((item) => draft.reportIds.includes(item.id)),
    postcards: options.postcards.filter((item) => draft.postcardIds.includes(item.id)),
    plans: options.plans.filter((item) => draft.planIds.includes(item.id)),
  }
  const selectedPhotos = draft.photoAssetIds.map((id) => photos.find((photo) => photo.id === id)?.url).filter((url): url is string => Boolean(url))
  const previewPost = { ...draft, photos: selectedPhotos.length ? selectedPhotos : attachments.postcards.map((item) => item.imageUrl), attachments, isDemo: false }
  return <>
    <form className="discovery-form share-form" onSubmit={(event) => { event.preventDefault(); setPreview(true) }}>
      <section className="share-section">
        <div className="share-section-title"><h2>这一程的照片</h2><span>{draft.photoAssetIds.length} / 12</span></div>
        <div className="share-photos">{photos.map((photo) => <button type="button" key={photo.id} aria-label={(draft.photoAssetIds.includes(photo.id) ? "取消选择照片 " : "选择照片 ") + (photos.indexOf(photo) + 1)} aria-pressed={draft.photoAssetIds.includes(photo.id)}
          disabled={!draft.photoAssetIds.includes(photo.id) && draft.photoAssetIds.length >= 12}
          onClick={() => setDraft({ ...draft, photoAssetIds: toggle(draft.photoAssetIds, photo.id) })}>
          <img src={resolveAssetUrl(photo.url)} alt="旅行照片" onError={handleImageError} /><span>{draft.photoAssetIds.includes(photo.id) ? <Check size={14} /> : null}</span>
        </button>)}<button type="button" className="share-add-photo" disabled={uploading || draft.photoAssetIds.length >= 12} onClick={() => fileInput.current?.click()}>{uploading ? <LoaderCircle className="discovery-spin" size={23} /> : <Camera size={23} />}<span>{uploading ? "上传中" : "添加照片"}</span></button></div>
        <input ref={fileInput} type="file" hidden multiple accept="image/jpeg,image/png,image/webp,image/heic,image/heif" onChange={(event) => void upload(event.target.files)} />
      </section>
      <section className="share-section share-writing">
        <div className="share-section-title"><h2>写下旅行体验</h2><button type="button" className="share-ai" disabled={assisting || !(draft.body.trim() || draft.recommendations.trim() || draft.pitfalls.trim())} onClick={() => void assist()}>{assisting ? <LoaderCircle className="discovery-spin" size={16} /> : <Sparkles size={16} />}{assisting ? "整理中…" : "AI 帮我整理"}</button></div>
        <label>标题<input required minLength={2} maxLength={60} value={draft.title} placeholder="给这一程起个标题" onChange={(event) => field("title", event.target.value)} /></label>
        <label>目的地<input required maxLength={60} value={draft.destination} placeholder="例如：杭州" onChange={(event) => field("destination", event.target.value)} /></label>
        <label>旅行感想<textarea required minLength={2} maxLength={5000} rows={5} value={draft.body} placeholder="这一程，哪些瞬间想留下？" onChange={(event) => field("body", event.target.value)} /></label>
        <div className="share-two-fields"><label>值得推荐<textarea rows={3} maxLength={2000} value={draft.recommendations} placeholder="喜欢的地方、路线或体验，可不填" onChange={(event) => field("recommendations", event.target.value)} /></label>
          <label>避雷与提醒<textarea rows={3} maxLength={2000} value={draft.pitfalls} placeholder="走过的弯路、需要注意的事，可不填" onChange={(event) => field("pitfalls", event.target.value)} /></label></div>
        <fieldset><legend>旅行主题 <small>最多 8 个，可不选</small></legend><TagPicker label="笔记旅行主题" selected={draft.tags} tags={DISCOVERY_TAGS} max={8} onChange={(tags) => setDraft({ ...draft, tags })} /></fieldset>
      </section>
      <section className="share-section"><div className="share-section-title"><h2>把旅行作品也带上</h2><span>可选</span></div><p className="share-hint">勾选的内容会出现在笔记中，发布前可以预览。</p>
        {options.reports.length + options.postcards.length + options.plans.length ? <div className="share-attachments">
          {options.reports.map((item) => <label key={item.id} className="discovery-check"><input type="checkbox" checked={draft.reportIds.includes(item.id)} disabled={!draft.reportIds.includes(item.id) && draft.reportIds.length >= 4} onChange={() => setDraft({ ...draft, reportIds: toggle(draft.reportIds, item.id) })} /><FileText size={19} /><span>人格报告<small>{item.title}</small></span></label>)}
          {options.postcards.map((item) => <label key={item.id} className="discovery-check"><input type="checkbox" checked={draft.postcardIds.includes(item.id)} disabled={!draft.postcardIds.includes(item.id) && draft.postcardIds.length >= 8} onChange={() => setDraft({ ...draft, postcardIds: toggle(draft.postcardIds, item.id) })} /><Images size={19} /><span>明信片<small>{item.title}</small></span></label>)}
          {options.plans.map((item) => <label key={item.id} className="discovery-check"><input type="checkbox" checked={draft.planIds.includes(item.id)} disabled={!draft.planIds.includes(item.id) && draft.planIds.length >= 4} onChange={() => setDraft({ ...draft, planIds: toggle(draft.planIds, item.id) })} /><Route size={19} /><span>行程路线<small>{item.destination} · {item.days.length} 天，仅分享路线概要</small></span></label>)}
        </div> : <p className="share-hint">这次旅行还没有作品，可以先分享照片和文字。</p>}
      </section>
      <div className="share-submit"><span>文字会暂存在本机</span><button type="submit" className="discovery-primary" disabled={!hydrated || uploading || assisting}>预览并发布</button></div>
    </form>
    {preview ? <DiscoveryDialog title="发布前看一眼" onClose={() => { if (!publishing) setPreview(false) }}>
      <div className="share-preview"><NoteBody post={previewPost} /></div><div className="share-preview-actions"><button type="button" disabled={publishing} className="discovery-secondary" onClick={() => setPreview(false)}>继续编辑</button><button type="button" className="discovery-primary" disabled={publishing} onClick={() => void publish()}>{publishing ? "发布中…" : "确认发布"}</button></div>
    </DiscoveryDialog> : null}
    {assisted ? <DiscoveryDialog title={assisted.source === "ai" ? "AI 整理的草稿" : "整理结果"} onClose={() => setAssisted(null)}>
      <div className="share-ai-preview"><p className="share-hint">{assisted.message}</p><h3>{assisted.title}</h3><p>{assisted.body}</p><div className="note-tags">{assisted.tags.map((tag) => <span key={tag}>#{tag}</span>)}</div></div>
      <div className="share-preview-actions"><button type="button" className="discovery-secondary" onClick={() => setAssisted(null)}>保留原文</button><button type="button" className="discovery-primary" onClick={() => { setDraft({ ...draft, title: assisted.title, body: assisted.body, tags: Array.from(new Set([...draft.tags, ...assisted.tags])).slice(0, 8) }); setAssisted(null) }}>采用草稿</button></div>
    </DiscoveryDialog> : null}
  </>
}

export function DiscoveryShareView() {
  const initialTripId = useSearchParams().get("tripId") ?? ""
  const { trips } = useApp()
  const [tripId, setTripId] = useState(initialTripId)
  const [options, setOptions] = useState<ShareOptions | null>(null)
  const [error, setError] = useState("")
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    if (!tripId) return
    let active = true
    getShareOptions(tripId).then((value) => { if (active) { setOptions(value); setError("") } }).catch((error) => { if (active) setError(error instanceof Error ? error.message : "旅行素材加载失败") })
    return () => { active = false }
  }, [tripId, revision])
  return <div className="app-page discovery-share-page">
    <header className="discovery-detail-header"><Link href={initialTripId ? "/trips/detail?tripId=" + encodeURIComponent(initialTripId) : "/discover"} className="discovery-icon" aria-label="返回"><ArrowLeft size={21} /></Link><div><strong>分享这次旅行</strong><span>把喜欢的体验，留给下一位旅行者</span></div><Link href="/discover" className="discovery-icon" aria-label="关闭分享"><X size={20} /></Link></header>
    <main className="discovery-scroll share-scroll">
      <label className="share-trip-picker">选择一次旅行<select aria-label="选择一次旅行" value={tripId} onChange={(event) => { setTripId(event.target.value); setOptions(null); setError("") }}><option value="">请选择</option>{trips.map((trip) => <option key={trip.id} value={trip.id}>{trip.title}</option>)}</select></label>
      {error ? <section className="discovery-empty" role="alert"><p>{error}</p><button className="discovery-secondary" onClick={() => setRevision((value) => value + 1)}>重试</button></section> : options?.trip.id === tripId ? <ShareForm key={tripId} options={options} /> : tripId ? <p className="discovery-empty">正在整理旅行素材…</p> : <section className="discovery-empty"><Camera size={32} /><h2>{trips.length ? "选择你想分享的那一程" : "先留下一次旅行"}</h2><p>照片、感想和旅行作品可以一起放进笔记。</p>{!trips.length ? <Link href="/create" className="discovery-primary">用照片创建旅行</Link> : null}</section>}
    </main>
    <BottomNav />
  </div>
}
