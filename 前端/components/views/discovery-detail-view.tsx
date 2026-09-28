"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Bookmark, EyeOff, Route, RotateCcw, Trash2 } from "lucide-react"
import { BottomNav } from "@/components/shared/bottom-nav"
import { ConfirmDialog } from "@/components/shared/confirm-dialog"
import { useApp } from "@/components/shared/app-context"
import { NoteBody } from "@/components/discovery/shared"
import { discoveryFeedback, getDiscoveryPost, withdrawDiscoveryPost, type DiscoveryPost } from "@/lib/discovery-api"

export function DiscoveryDetailView() {
  const id = useSearchParams().get("postId") ?? ""
  const router = useRouter()
  const { toast, toastError, startPlanningFromSeed, hasUnsavedDraft } = useApp()
  const [post, setPost] = useState<DiscoveryPost | null>(null)
  const [error, setError] = useState("")
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<"withdraw" | "plan" | null>(null)
  useEffect(() => {
    let active = true
    getDiscoveryPost(id).then((value) => { if (active) { setPost(value); setError("") } }).catch((error) => { if (active) setError(error instanceof Error ? error.message : "笔记加载失败") })
    return () => { active = false }
  }, [id, revision])
  async function action(kind: "save" | "unsave" | "dismiss" | "restore") {
    if (!post || busy) return
    setBusy(true)
    try {
      setPost({ ...post, ...await discoveryFeedback(id, kind) })
      toast(kind === "save" ? "已收藏" : kind === "unsave" ? "已取消收藏" : kind === "restore" ? "已恢复推荐" : "将不再推荐这篇笔记", "success")
    } catch (error) { toastError(error) } finally { setBusy(false) }
  }
  function plan() {
    if (!post) return
    const references = [
      post.recommendations && "笔记中的推荐：" + post.recommendations,
      post.pitfalls && "笔记中的提醒：" + post.pitfalls,
      ...(post.attachments.plans || []).map((route) => "路线参考：" + route.days.map((day) => day.stops.join(" → ")).join("；")),
    ].filter(Boolean).join("\n").slice(0, 1800)
    startPlanningFromSeed({
      text: "我想去" + post.destination + "。参考旅行笔记《" + post.title + "》，我对" + (post.tags.slice(0, 3).join("、") || "当地旅行") + "感兴趣。请先和我确认日期、出发地和旅行安排，再规划路线。以下是笔记资料，出行信息需要重新核对。" + (post.isDemo ? "这篇是演示笔记。" : "") + (references ? "\n\n" + references : ""),
      sourceLabel: "旅行发现 · " + post.title, returnHref: "/discover/detail?postId=" + encodeURIComponent(id),
    })
    router.push("/planning")
  }
  async function withdraw() {
    if (busy) return
    setBusy(true)
    try { await withdrawDiscoveryPost(id); toast("笔记已撤回，原来的旅行作品仍然保留", "success"); router.replace("/discover") }
    catch (error) { toastError(error); setBusy(false); setConfirm(null) }
  }
  return <div className="app-page discovery-detail-page">
    <header className="discovery-detail-header"><Link href="/discover" className="discovery-icon" aria-label="返回旅行发现"><ArrowLeft size={21} /></Link>
      <div><strong>{post?.author || "旅行笔记"}</strong><span>{post ? (post.isDemo ? "演示笔记 · " : "") + post.createdAt.slice(0, 10) : "这一程的故事"}</span></div>
      {post?.isOwn ? <button className="discovery-icon" type="button" aria-label="撤回笔记" onClick={() => setConfirm("withdraw")}><Trash2 size={19} /></button> : null}
    </header>
    <main className="discovery-scroll note-detail-scroll">
      {error ? <div className="discovery-empty" role="alert"><p>{error}</p><button className="discovery-secondary" onClick={() => setRevision((value) => value + 1)}>重试</button></div> : post ? <NoteBody post={post} /> : <div className="discovery-skeleton note-loading" aria-label="正在加载笔记" />}
    </main>
    {post ? <footer className="note-actions">
      <button type="button" className={"discovery-secondary" + (post.saved ? " is-saved" : "")} disabled={busy} aria-pressed={post.saved} onClick={() => void action(post.saved ? "unsave" : "save")}><Bookmark size={18} fill={post.saved ? "currentColor" : "none"} />{post.saved ? "已收藏" : "收藏"}</button>
      {!post.isOwn ? <button type="button" className="discovery-icon" disabled={busy} aria-label={post.dismissed ? "恢复推荐" : "不感兴趣"} onClick={() => void action(post.dismissed ? "restore" : "dismiss")}>{post.dismissed ? <RotateCcw size={18} /> : <EyeOff size={18} />}</button> : null}
      <button type="button" className="discovery-primary" onClick={() => hasUnsavedDraft ? setConfirm("plan") : plan()}><Route size={18} />规划这一程</button>
    </footer> : null}
    <BottomNav />
    <ConfirmDialog open={confirm === "withdraw"} title="撤回这篇笔记？" description="撤回后，发现和收藏中将不再显示。原来的旅行、照片和作品都会保留。" onClose={() => { if (!busy) setConfirm(null) }} actions={[{ label: busy ? "撤回中…" : "撤回笔记", onClick: () => void withdraw(), variant: "danger" }, { label: "继续保留", onClick: () => { if (!busy) setConfirm(null) }, variant: "ghost" }]} />
    <ConfirmDialog open={confirm === "plan"} title="开始新的旅行规划？" description="当前有一份尚未保存的行程草稿，开始新规划会替换它。" onClose={() => setConfirm(null)} actions={[{ label: "开始新规划", onClick: plan, variant: "primary" }, { label: "保留原草稿", onClick: () => setConfirm(null), variant: "ghost" }]} />
  </div>
}
