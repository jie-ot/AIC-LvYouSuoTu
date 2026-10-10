"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { Bookmark, Compass, EyeOff, MapPin, Plus, Search, RotateCcw } from "lucide-react"
import { BottomNav } from "@/components/shared/bottom-nav"
import { useApp } from "@/components/shared/app-context"
import { useAuth } from "@/components/shared/auth-context"
import { AccountMenu } from "@/components/shared/account-menu"
import { DiscoveryGrid } from "@/components/discovery/shared"
import { handleImageError, resolveAssetUrl } from "@/lib/asset"
import { DISCOVERY_TAGS, discoveryFeedback, getDiscoveryFeed, recordDiscoverySearch, type Feed, type FeedMode } from "@/lib/discovery-api"

export function DiscoveryView() {
  const { toast, toastError } = useApp()
  const { user } = useAuth()
  const [feed, setFeed] = useState<Feed | null>(null)
  const [query, setQuery] = useState("")
  const [search, setSearch] = useState("")
  const [topic, setTopic] = useState("")
  const [mode, setMode] = useState<FeedMode>("recommended")
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [more, setMore] = useState(false)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const epoch = useRef(0)
  const scroll = useRef<HTMLDivElement>(null)
  const semanticStatus = feed?.semantic?.status
  const itemCount = feed?.items.length ?? 0

  useEffect(() => {
    const request = ++epoch.current
    let active = true
    const task = window.setTimeout(() => { setLoading(true); setError(false); scroll.current?.scrollTo({ top: 0 }) }, 0)
    getDiscoveryFeed(query, topic, mode).then((value) => { if (active && request === epoch.current) setFeed(value) })
      .catch(() => { if (active) setError(true) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false; window.clearTimeout(task) }
  }, [query, topic, mode, revision])

  useEffect(() => {
    if (mode !== "recommended" || semanticStatus !== "building" || itemCount > 20) return
    let active = true
    let attempts = 0
    const request = epoch.current
    let timer: ReturnType<typeof setTimeout>
    const check = async () => {
      // Never move cards while the reader is scrolling through the list.
      if (!active || (scroll.current?.scrollTop ?? 0) > 24 || request !== epoch.current) return
      try {
        const next = await getDiscoveryFeed(query, topic, mode)
        if (!active || request !== epoch.current) return
        if (next.semantic?.status !== "building") {
          if ((scroll.current?.scrollTop ?? 0) <= 24) setFeed(next)
          return
        }
      } catch { /* The existing feed remains usable while indexing is unavailable. */ }
      if (++attempts < 12 && active) timer = setTimeout(check, 4000)
    }
    timer = setTimeout(check, 4000)
    return () => { active = false; clearTimeout(timer) }
  }, [semanticStatus, itemCount, mode, query, topic, revision])

  function submitSearch() {
    const value = search.trim()
    setQuery(value)
    if (value && !user?.readOnly) void recordDiscoverySearch(value).catch(() => {})
  }
  async function loadMore() {
    if (feed?.nextOffset == null || more) return
    const request = epoch.current
    setMore(true)
    try {
      // Continue the first page's ranking while an index is being prepared.
      const next = await getDiscoveryFeed(query, topic, mode, feed.nextOffset, feed.semantic?.status === "ready")
      if (request === epoch.current) setFeed((previous) => previous ? { ...next, items: [...previous.items, ...next.items.filter((item) => !previous.items.some((old) => old.id === item.id))] } : next)
    } catch (error) { toastError(error) } finally { setMore(false) }
  }
  async function act(id: string, action: "save" | "unsave" | "dismiss" | "restore") {
    if (busy) return
    setBusy(id)
    try {
      const result = await discoveryFeedback(id, action)
      setFeed((previous) => previous ? { ...previous, items: previous.items.map((item) => item.id === id ? { ...item, ...result } : item) } : previous)
      toast(action === "save" ? "已收藏，可以带去规划下一程" : action === "dismiss" ? "已减少这篇内容，可在已隐藏中恢复" : action === "restore" ? "已恢复推荐" : "已取消收藏", "success")
      setRevision((value) => value + 1)
    } catch (error) { toastError(error) } finally { setBusy(null) }
  }
  return <div className="app-page discovery-page">
    <header className="discovery-header">
      <div className="discovery-heading"><div><div className="collection-brand-row"><div className="brand-mark">旅有所图 / 发现</div><AccountMenu /></div><h1>旅行发现<span>下一程，从这里开始</span></h1></div>
        <Link href="/discover/share" className="discovery-primary"><Plus size={18} /><span>分享旅行</span></Link></div>
      <div className="discovery-search-row"><form className="discovery-search" role="search" onSubmit={(event) => { event.preventDefault(); submitSearch() }}>
        <Search size={19} /><input aria-label="搜索旅行笔记" value={search} onChange={(event) => setSearch(event.target.value)} maxLength={100} placeholder="搜目的地、旅行方式、推荐与避雷" />
        {search ? <button type="button" onClick={() => { setSearch(""); setQuery("") }} aria-label="清空搜索">清空</button> : null}
        <button type="submit">搜索</button></form></div>
      <div className="discovery-tabs" role="group" aria-label="笔记范围">{([
        ["recommended", "为你推荐"], ["saved", "我的收藏"], ["mine", "我的分享"], ["hidden", "已隐藏"],
      ] as [FeedMode, string][]).map(([key, label]) => <button type="button" key={key} aria-pressed={mode === key} onClick={() => setMode(key)}>{label}</button>)}</div>
      <div className="discovery-topics" role="group" aria-label="旅行主题">{["", ...DISCOVERY_TAGS].map((tag) => <button type="button" key={tag} aria-pressed={topic === tag} onClick={() => setTopic(tag)}>{tag || "全部"}</button>)}</div>
    </header>
    <main ref={scroll} className="discovery-scroll">
      {feed && !query && mode === "recommended" ? <div className="discovery-intent"><Compass size={16} aria-hidden /><p>发现下一程的灵感</p>
        <span>{feed.demoCount ? feed.demoCount + " 篇演示笔记" : "按你的旅行需求推荐"}</span></div> : null}
      {query ? <p className="discovery-result-label">“{query}”的搜索结果{!loading && feed ? " · " + feed.total + " 篇" : ""}</p> : null}
      {error ? <section className="discovery-empty" role="alert"><p>旅行笔记暂时没能加载</p><button className="discovery-secondary" onClick={() => setRevision((value) => value + 1)}>重新加载</button></section> :
        loading ? <div aria-label="正在加载笔记"><DiscoveryGrid>{Array.from({ length: 6 }, (_, index) => <div className="discovery-skeleton" key={index} />)}</DiscoveryGrid></div> :
        feed?.items.length ? <><DiscoveryGrid>
          {feed.items.map((post, index) => <article key={post.id} className={"discovery-card cover-shape-" + index % 4}>
            <Link href={"/discover/detail?postId=" + encodeURIComponent(post.id)} className="discovery-card-link">
              <div className="discovery-cover">{post.cover ? <img src={resolveAssetUrl(post.cover)} alt={post.destination + "旅行封面"} loading={index < 4 ? "eager" : "lazy"} onError={handleImageError} /> : <div className="discovery-no-cover"><Compass size={36} /><span>{post.destination}</span></div>}
                {post.isDemo ? <span className="discovery-demo-badge">演示</span> : null}
                <span className="discovery-place"><MapPin size={12} />{post.destination}</span>
                {post.attachmentKinds.length ? <span className="discovery-attachment-badge">附旅行作品</span> : null}
              </div><div className="discovery-card-copy"><h2>{post.title}</h2><p className="discovery-excerpt">{post.excerpt}</p>
                <p className="discovery-card-tags">{post.tags.slice(0, 2).map((tag) => "#" + tag).join("  ")}</p></div>
            </Link>
            <footer><span className={"discovery-avatar avatar-" + index % 5}>{post.author.slice(0, 1)}</span><span className="discovery-author">{post.author}</span>
              <button className={"discovery-icon" + (post.saved ? " is-saved" : "")} type="button" disabled={busy === post.id} aria-label={(post.saved ? "取消收藏：" : "收藏：") + post.title} aria-pressed={post.saved} onClick={() => void act(post.id, post.saved ? "unsave" : "save")}><Bookmark size={17} fill={post.saved ? "currentColor" : "none"} /></button>
              <button className="discovery-icon" type="button" disabled={busy === post.id} aria-label={(post.dismissed ? "恢复：" : "不感兴趣：") + post.title} onClick={() => void act(post.id, post.dismissed ? "restore" : "dismiss")}>{post.dismissed ? <RotateCcw size={15} /> : <EyeOff size={15} />}</button>
            </footer>
          </article>)}
        </DiscoveryGrid>{feed.nextOffset !== null ? <button type="button" className="discovery-load-more" disabled={more} onClick={() => void loadMore()}>{more ? "加载中…" : "再看看更多旅行"}</button> : <p className="discovery-end">这次就看到这里，下一程等你分享。</p>}</> :
        <section className="discovery-empty"><Compass size={32} /><h2>{query ? "还没有找到相关笔记" : mode === "saved" ? "把喜欢的旅行先收藏起来" : mode === "mine" ? "分享你的第一篇旅行笔记" : mode === "hidden" ? "还没有隐藏的笔记" : "暂时没有合适的笔记"}</h2><p>{query ? "换一个目的地或关键词试试。" : mode === "mine" ? "照片、明信片、人格报告和行程，都可以一起分享。" : "可以换个主题，看看其他旅行。"}</p>{mode === "mine" ? <Link href="/discover/share" className="discovery-primary">分享旅行</Link> : <button type="button" className="discovery-secondary" onClick={() => { setTopic(""); setQuery(""); setSearch(""); setMode("recommended") }}>随处看看</button>}</section>}
    </main>
    <BottomNav />
  </div>
}
